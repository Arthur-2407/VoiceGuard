package com.voiceguard.client.ui.screens

import android.Manifest
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.navigation.NavController
import com.voiceguard.client.network.WebSocketClient
import com.voiceguard.client.ui.MainViewModel
import com.voiceguard.client.ui.theme.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject

@Composable
fun LiveMonitorScreen(navController: NavController, viewModel: MainViewModel) {
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    
    var isRecording by remember { mutableStateOf(false) }
    var hasPermission by remember { mutableStateOf(
        ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
    ) }
    
    val permissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        hasPermission = it
    }
    
    var riskScore by remember { mutableStateOf(0.0) }
    var alertLevel by remember { mutableStateOf("SAFE") }
    
    var webSocketClient by remember { mutableStateOf<WebSocketClient?>(null) }
    var audioRecord by remember { mutableStateOf<AudioRecord?>(null) }

    DisposableEffect(Unit) {
        onDispose {
            isRecording = false
            audioRecord?.stop()
            audioRecord?.release()
            webSocketClient?.disconnect()
        }
    }
    
    LaunchedEffect(webSocketClient?.lastMessage?.collectAsState()?.value) {
        webSocketClient?.lastMessage?.value?.let { msg ->
            try {
                val json = JSONObject(msg)
                if (json.optString("type") == "risk_update") {
                    riskScore = json.getDouble("risk_score")
                    alertLevel = json.getString("alert_level")
                }
            } catch (e: Exception) {}
        }
    }

    Column(modifier = Modifier.fillMaxSize().padding(24.dp)) {
        Text("LIVE MONITOR", style = MaterialTheme.typography.headlineMedium, color = TextPrimary)
        Text("REAL-TIME TELEMETRY UPLINK", style = MaterialTheme.typography.labelSmall, color = CyberBlue)
        
        Spacer(modifier = Modifier.height(32.dp))
        
        SectionHeader("UPLINK CONTROL")
        VoiceGuardCard {
            if (!hasPermission) {
                Text("MICROPHONE ACCESS REQUIRED", style = MaterialTheme.typography.labelSmall, color = StatusWarning)
                Spacer(modifier = Modifier.height(16.dp))
                Button(
                    onClick = { permissionLauncher.launch(Manifest.permission.RECORD_AUDIO) },
                    colors = ButtonDefaults.buttonColors(containerColor = CyberBlue)
                ) {
                    Text("AUTHORIZE", style = MaterialTheme.typography.labelSmall, color = DeepSpaceBackground)
                }
            } else {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Column {
                        Text("STREAM STATUS", style = MaterialTheme.typography.labelSmall, color = TextTertiary)
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = if (isRecording) "TRANSMITTING" else "STANDBY",
                            style = MaterialTheme.typography.bodyMedium,
                            color = if (isRecording) StatusOnline else TextSecondary
                        )
                    }
                    Button(
                        onClick = {
                            if (isRecording) {
                                isRecording = false
                                audioRecord?.stop()
                                webSocketClient?.disconnect()
                            } else {
                                val url = viewModel.serverUrl.value
                                if (url != null) {
                                    webSocketClient = WebSocketClient(viewModel.connectionManager.okHttpClient, url)
                                    webSocketClient?.connect()
                                    
                                    try {
                                        val bufferSize = AudioRecord.getMinBufferSize(
                                            16000,
                                            AudioFormat.CHANNEL_IN_MONO,
                                            AudioFormat.ENCODING_PCM_16BIT
                                        )
                                        if (bufferSize <= 0) throw IllegalStateException("Invalid buffer size")
                                        audioRecord = AudioRecord(
                                            MediaRecorder.AudioSource.MIC,
                                            16000,
                                            AudioFormat.CHANNEL_IN_MONO,
                                            AudioFormat.ENCODING_PCM_16BIT,
                                            bufferSize * 2
                                        )
                                        if (audioRecord?.state != AudioRecord.STATE_INITIALIZED) {
                                            throw IllegalStateException("AudioRecord initialization failed")
                                        }
                                        audioRecord?.startRecording()
                                        isRecording = true
                                        
                                        coroutineScope.launch(Dispatchers.IO) {
                                            val buffer = ByteArray(bufferSize)
                                            while (isActive && isRecording) {
                                                val read = audioRecord?.read(buffer, 0, buffer.size) ?: 0
                                                if (read > 0) {
                                                    webSocketClient?.sendAudio(buffer.copyOf(read))
                                                }
                                            }
                                        }
                                    } catch (e: SecurityException) {}
                                }
                            }
                        },
                        colors = ButtonDefaults.buttonColors(
                            containerColor = if (isRecording) StatusCritical else CyberBlue,
                            contentColor = TextPrimary
                        )
                    ) {
                        Text(if (isRecording) "TERMINATE" else "INITIALIZE", style = MaterialTheme.typography.labelSmall)
                    }
                }
            }
        }
        
        Spacer(modifier = Modifier.height(24.dp))
        
        if (isRecording) {
            SectionHeader("LIVE TELEMETRY")
            VoiceGuardCard {
                val riskColor = when (alertLevel.uppercase()) {
                    "CRITICAL" -> StatusCritical
                    "HIGH" -> StatusWarning
                    "MODERATE" -> StatusWarning
                    else -> StatusOnline
                }
                
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.Top
                ) {
                    MetricDisplay(
                        label = "CURRENT RISK SCORE",
                        value = String.format("%.3f", riskScore),
                        color = riskColor
                    )
                    StatusBadge(text = alertLevel, color = riskColor)
                }
                
                Spacer(modifier = Modifier.height(24.dp))
                
                // Animated live indicator (simple UI representation of active data)
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(4.dp)
                        .clip(RoundedCornerShape(2.dp))
                        .background(DividerColor)
                ) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth(if (riskScore > 0) riskScore.toFloat().coerceIn(0.05f, 1f) else 0.05f)
                            .height(4.dp)
                            .clip(RoundedCornerShape(2.dp))
                            .background(riskColor)
                    )
                }
                Spacer(modifier = Modifier.height(8.dp))
                Text("RISK THRESHOLD METER", style = MaterialTheme.typography.labelSmall, color = TextTertiary)
            }
        }
    }
}
