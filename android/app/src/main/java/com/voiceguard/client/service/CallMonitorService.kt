package com.voiceguard.client.service

import android.app.*
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.telephony.TelephonyCallback
import android.telephony.TelephonyManager
import android.util.Log
import androidx.core.app.NotificationCompat
import com.voiceguard.client.MainActivity
import com.voiceguard.client.audio.AudioSourceType
import com.voiceguard.client.audio.RealTimeAudioPipeline
import com.voiceguard.client.model.*
import com.voiceguard.client.network.WebSocketEventClient
import com.voiceguard.client.network.WsEvent
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import okhttp3.OkHttpClient

class CallMonitorService : Service() {
    private lateinit var repository: CallMonitorRepository

    companion object {
        private const val CHANNEL_ID = "VoiceGuardCallMonitor"
        private const val ALERT_CHANNEL_ID = "VoiceGuardSecurityAlert"
        private const val NOTIFICATION_ID = 1001
        private const val ALERT_NOTIFICATION_ID = 1002
    }

    private var telephonyManager: TelephonyManager? = null
    private val serviceScope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var monitoringJob: Job? = null
    
    private var webSocketClient: WebSocketEventClient? = null
    private var audioPipeline: RealTimeAudioPipeline? = null
    private val okHttpClient = OkHttpClient()

    override fun onCreate() {
        super.onCreate()
        repository = CallMonitorRepository.getInstance(applicationContext)
        createNotificationChannels()
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(
                    NOTIFICATION_ID, 
                    buildStatusNotification("Monitoring for active calls..."),
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE else 0
                )
            } else {
                startForeground(NOTIFICATION_ID, buildStatusNotification("Monitoring for active calls..."))
            }
        } catch (e: Exception) {
            Log.e("CallMonitorService", "Failed to start foreground service: ${e.message}")
            repository.updateTelemetry { it.copy(
                monitorState = MonitorState.UNAVAILABLE, 
                diagnosticReason = "FGS Start Failed: ${e.message}"
            ) }
            stopSelf()
            return
        }
        
        telephonyManager = getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager
        
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            telephonyManager?.registerTelephonyCallback(mainExecutor, object : TelephonyCallback(), TelephonyCallback.CallStateListener {
                override fun onCallStateChanged(state: Int) {
                    handleCallStateChange(state)
                }
            })
        } else {
            @Suppress("DEPRECATION")
            telephonyManager?.listen(object : android.telephony.PhoneStateListener() {
                @Deprecated("Deprecated in Java")
                override fun onCallStateChanged(state: Int, phoneNumber: String?) {
                    handleCallStateChange(state)
                }
            }, android.telephony.PhoneStateListener.LISTEN_CALL_STATE)
        }
    }

    private fun getAudioRoute(): String {
        val audioManager = getSystemService(Context.AUDIO_SERVICE) as android.media.AudioManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val commDevice = audioManager.communicationDevice
            if (commDevice != null) {
                return when (commDevice.type) {
                    android.media.AudioDeviceInfo.TYPE_BLUETOOTH_SCO,
                    android.media.AudioDeviceInfo.TYPE_BLUETOOTH_A2DP,
                    android.media.AudioDeviceInfo.TYPE_BLE_HEADSET -> "BLUETOOTH"
                    android.media.AudioDeviceInfo.TYPE_BUILTIN_SPEAKER -> "SPEAKERPHONE"
                    android.media.AudioDeviceInfo.TYPE_WIRED_HEADSET,
                    android.media.AudioDeviceInfo.TYPE_WIRED_HEADPHONES,
                    android.media.AudioDeviceInfo.TYPE_USB_HEADSET -> "WIRED_HEADSET"
                    android.media.AudioDeviceInfo.TYPE_BUILTIN_EARPIECE -> "EARPIECE"
                    else -> "OTHER"
                }
            }
        }
        return when {
            @Suppress("DEPRECATION")
            audioManager.isBluetoothScoOn -> "BLUETOOTH"
            @Suppress("DEPRECATION")
            audioManager.isSpeakerphoneOn -> "SPEAKERPHONE"
            @Suppress("DEPRECATION")
            audioManager.isWiredHeadsetOn -> "WIRED_HEADSET"
            else -> "EARPIECE"
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        return START_STICKY
    }

    private fun handleCallStateChange(state: Int) {
        when (state) {
            TelephonyManager.CALL_STATE_OFFHOOK -> {
                Log.d("CallMonitorService", "Call is active. Starting monitor.")
                repository.updateTelemetry { it.copy(callState = TelephonyCallState.ACTIVE) }
                if (repository.telemetry.value.monitorState != MonitorState.ANALYZING) {
                    startMonitoring()
                }
            }
            TelephonyManager.CALL_STATE_IDLE -> {
                Log.d("CallMonitorService", "Call ended. Stopping monitor.")
                stopMonitoring()
                val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
                notificationManager.cancel(ALERT_NOTIFICATION_ID)
                updateStatusNotification("Monitoring for active calls...")
            }
            TelephonyManager.CALL_STATE_RINGING -> {
                Log.d("CallMonitorService", "Call ringing.")
                repository.updateTelemetry { it.copy(callState = TelephonyCallState.RINGING) }
            }
        }
    }

    private fun startMonitoring() {
        val serverUrl = repository.connectionManager.serverUrl.value
        if (serverUrl == null) {
            repository.updateTelemetry { it.copy(
                monitorState = MonitorState.UNAVAILABLE,
                diagnosticReason = "Cannot monitor: Server URL not provided"
            ) }
            updateStatusNotification("Cannot monitor: Server disconnected")
            return
        }

        monitoringJob?.cancel()
        monitoringJob = serviceScope.launch {
            try {
                repository.updateTelemetry { it.copy(monitorState = MonitorState.INITIALIZING) }
                updateStatusNotification("Initializing monitoring...")
                
                // Initialize Audio first
                repository.updateTelemetry { it.copy(audioState = AudioCaptureState.INITIALIZING) }
                
                val currentRoute = getAudioRoute()
                val captureModeString = "ACOUSTIC_FALLBACK ($currentRoute)"
                
                audioPipeline = RealTimeAudioPipeline(AudioSourceType.VOICE_COMMUNICATION, { data ->
                    webSocketClient?.sendAudio(data)
                    repository.updateTelemetry { 
                        it.copy(
                            framesCaptured = audioPipeline?.framesCaptured ?: it.framesCaptured,
                            framesSent = it.framesSent + 1
                        ) 
                    }
                }, { errorMsg ->
                    repository.updateTelemetry { it.copy(
                        audioState = AudioCaptureState.UNAVAILABLE,
                        diagnosticReason = errorMsg
                    ) }
                })
                
                audioPipeline?.start()
                repository.updateTelemetry { it.copy(
                    audioState = AudioCaptureState.CAPTURING,
                    audioSource = "MIXED_ACOUSTIC",
                    captureMode = captureModeString
                ) }

                // Connect Backend
                repository.updateTelemetry { it.copy(backendState = BackendState.CONNECTING) }
                webSocketClient = WebSocketEventClient(okHttpClient, serverUrl)
                webSocketClient?.connect()
                
                // Listen to WS events
                launch {
                    webSocketClient?.events?.collect { event ->
                        when (event) {
                            is WsEvent.Connected -> {
                                repository.updateTelemetry { it.copy(
                                    backendState = BackendState.CONNECTED
                                ) }
                            }
                            is WsEvent.SessionStarted -> {
                                repository.updateTelemetry { it.copy(
                                    detectorState = if (event.detectorReady) DetectorState.READY else DetectorState.UNAVAILABLE
                                ) }
                            }
                            is WsEvent.RiskUpdate -> {
                                repository.updateTelemetry { it.copy(
                                    hasValidResult = true,
                                    currentRisk = event.riskScore,
                                    alertLevel = event.alertLevel,
                                    lastResultTimestamp = System.currentTimeMillis(),
                                    monitorState = MonitorState.ANALYZING
                                ) }
                                if (event.alertLevel == "CRITICAL" || event.alertLevel == "HIGH") {
                                    triggerSecurityAlert(event.riskScore, event.alertLevel)
                                }
                            }
                            is WsEvent.StatusUpdate -> {
                                if (!repository.telemetry.value.hasValidResult) {
                                    repository.updateTelemetry { it.copy(
                                        alertLevel = event.status,
                                        monitorState = if (event.status == "WAITING_FOR_DATA") MonitorState.STREAMING else it.monitorState
                                    ) }
                                }
                            }
                            is WsEvent.Disconnected -> {
                                repository.updateTelemetry { it.copy(
                                    monitorState = MonitorState.UNAVAILABLE,
                                    backendState = BackendState.ERROR,
                                    detectorState = DetectorState.UNAVAILABLE,
                                    diagnosticReason = "WebSocket Disconnected"
                                ) }
                                updateStatusNotification("Monitoring unavailable: WebSocket Disconnected")
                            }
                            is WsEvent.Error -> {
                                repository.updateTelemetry { it.copy(
                                    monitorState = MonitorState.UNAVAILABLE,
                                    backendState = BackendState.ERROR,
                                    detectorState = DetectorState.UNAVAILABLE,
                                    diagnosticReason = "Backend Error: ${event.message}"
                                ) }
                                updateStatusNotification("Monitoring unavailable: ${event.message}")
                            }
                            else -> {}
                        }
                    }
                }

                // Wait briefly for WS to connect before sending control metadata
                delay(500)

                webSocketClient?.sendControlMessage("start_call_monitor", mapOf(
                    "audio_source" to "MIXED_ACOUSTIC",
                    "capture_mode" to captureModeString
                ))
                
                // Do not assume analyzing until we get a result, but we can indicate recording.
                updateStatusNotification("Connecting and initializing audio ($currentRoute)...")
                
                // Begin audio stream
                audioPipeline?.streamData()

            } catch (e: Exception) {
                Log.e("CallMonitorService", "Error starting monitor", e)
                val reason = when (e) {
                    is SecurityException -> "Permission Denied: ${e.message}"
                    is IllegalStateException -> "AudioInit Error: ${e.message}"
                    is java.io.IOException -> "Network Error: ${e.message}"
                    else -> "Unknown Error: ${e.message}"
                }
                repository.updateTelemetry { it.copy(
                    monitorState = MonitorState.UNAVAILABLE,
                    audioState = if (e is SecurityException || e is IllegalStateException) AudioCaptureState.UNAVAILABLE else it.audioState,
                    backendState = if (e is java.io.IOException) BackendState.ERROR else it.backendState,
                    diagnosticReason = reason
                ) }
                updateStatusNotification("Monitoring unavailable: $reason")
                
                // Ensure partial cleanup
                stopMonitoring()
            }
        }
    }

    private fun stopMonitoring() {
        monitoringJob?.cancel()
        monitoringJob = null
        audioPipeline?.stop()
        audioPipeline = null
        
        webSocketClient?.sendControlMessage("stop_call_monitor")
        webSocketClient?.disconnect()
        webSocketClient = null
        
        // Force fully clean state upon call stop
        repository.resetTelemetry()
    }

    private fun triggerSecurityAlert(risk: Double, level: String) {
        val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
            putExtra("navigate_to", "call_monitor")
        }
        val pendingIntent = PendingIntent.getActivity(
            this, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val notification = NotificationCompat.Builder(this, ALERT_CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle("⚠ POSSIBLE CLONED VOICE DETECTED")
            .setContentText("Risk: $level (${String.format("%.3f", risk)}). Do not share OTP or sensitive data.")
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setFullScreenIntent(pendingIntent, true)
            .setContentIntent(pendingIntent)
            .setAutoCancel(false)
            .setOngoing(true)
            .build()

        notificationManager.notify(ALERT_NOTIFICATION_ID, notification)
    }

    private fun updateStatusNotification(text: String) {
        val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        notificationManager.notify(NOTIFICATION_ID, buildStatusNotification(text))
    }

    private fun buildStatusNotification(text: String): Notification {
        val intent = Intent(this, MainActivity::class.java).apply {
            putExtra("navigate_to", "call_monitor")
        }
        val pendingIntent = PendingIntent.getActivity(
            this, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("VoiceGuard Call Monitor")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .build()
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            
            val statusChannel = NotificationChannel(
                CHANNEL_ID,
                "Call Monitor Status",
                NotificationManager.IMPORTANCE_LOW
            )
            manager.createNotificationChannel(statusChannel)
            
            val alertChannel = NotificationChannel(
                ALERT_CHANNEL_ID,
                "Security Alerts",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "Critical alerts for potential deepfake callers"
                enableVibration(true)
            }
            manager.createNotificationChannel(alertChannel)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        super.onDestroy()
        stopMonitoring()
        serviceScope.cancel()
    }
}
