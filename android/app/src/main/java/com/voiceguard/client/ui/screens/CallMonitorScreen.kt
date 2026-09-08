package com.voiceguard.client.ui.screens

import android.content.Intent
import android.os.Build
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
import androidx.navigation.NavController
import com.voiceguard.client.service.CallMonitorService
import androidx.core.content.ContextCompat
import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import com.voiceguard.client.ui.MainViewModel
import com.voiceguard.client.ui.theme.*
import com.voiceguard.client.model.*

@Suppress("UNUSED_PARAMETER")
@Composable
fun CallMonitorScreen(navController: NavController, viewModel: MainViewModel) {
    val context = LocalContext.current
    
    val telemetry by viewModel.telemetry.collectAsState()

    val requiredPermissions = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        arrayOf(Manifest.permission.RECORD_AUDIO, Manifest.permission.READ_PHONE_STATE, Manifest.permission.POST_NOTIFICATIONS)
    } else {
        arrayOf(Manifest.permission.RECORD_AUDIO, Manifest.permission.READ_PHONE_STATE)
    }

    var permissionsGranted by remember { 
        mutableStateOf(requiredPermissions.all {
            ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED
        })
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        permissionsGranted = requiredPermissions.all { permissions[it] == true }
    }

    LaunchedEffect(Unit) {
        if (!permissionsGranted) {
            permissionLauncher.launch(requiredPermissions)
        }
    }

    // Start the service automatically only when permissions are granted
    LaunchedEffect(permissionsGranted) {
        if (permissionsGranted) {
            val intent = Intent(context, CallMonitorService::class.java)
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    context.startForegroundService(intent)
                } else {
                    context.startService(intent)
                }
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }
    }

    Column(modifier = Modifier.fillMaxSize().padding(24.dp)) {
        Text("CALL MONITOR", style = MaterialTheme.typography.headlineMedium, color = TextPrimary)
        Text("REAL-TIME DEEPFAKE DETECTION", style = MaterialTheme.typography.labelSmall, color = CyberBlue)
        
        Spacer(modifier = Modifier.height(32.dp))
        
        if (!permissionsGranted) {
            VoiceGuardCard(containerColor = ElevatedSurface) {
                Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxWidth()) {
                    Text("PERMISSIONS REQUIRED", style = MaterialTheme.typography.titleMedium, color = StatusWarning)
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        "VoiceGuard requires Microphone and Phone State permissions to securely monitor the acoustic fallback audio during calls.",
                        style = MaterialTheme.typography.bodySmall,
                        color = TextSecondary,
                        textAlign = androidx.compose.ui.text.style.TextAlign.Center
                    )
                    Spacer(modifier = Modifier.height(16.dp))
                    Button(onClick = { permissionLauncher.launch(requiredPermissions) }) {
                        Text("GRANT PERMISSIONS")
                    }
                }
            }
        } else {
        
        SectionHeader("SYSTEM STATUS")
        VoiceGuardCard {
            Column(modifier = Modifier.fillMaxWidth()) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    StatusRow("CALL", telemetry.callState.name, if (telemetry.callState == TelephonyCallState.ACTIVE) StatusOnline else TextSecondary)
                    StatusRow("MONITOR", telemetry.monitorState.name, when(telemetry.monitorState) {
                        MonitorState.ANALYZING -> StatusOnline
                        MonitorState.STREAMING -> StatusWarning
                        MonitorState.UNAVAILABLE -> StatusCritical
                        MonitorState.INITIALIZING -> StatusWarning
                        else -> TextSecondary
                    })
                }
                Spacer(modifier = Modifier.height(8.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    StatusRow("AUDIO", telemetry.audioState.name, when(telemetry.audioState) {
                        AudioCaptureState.CAPTURING -> StatusOnline
                        AudioCaptureState.UNAVAILABLE -> StatusCritical
                        else -> TextSecondary
                    })
                    StatusRow("BACKEND", telemetry.backendState.name, when(telemetry.backendState) {
                        BackendState.CONNECTED -> StatusOnline
                        BackendState.ERROR -> StatusCritical
                        else -> TextSecondary
                    })
                }
                Spacer(modifier = Modifier.height(8.dp))
                StatusRow("DETECTOR", telemetry.detectorState.name, if (telemetry.detectorState == DetectorState.READY) StatusOnline else TextSecondary)
            }
        }
        
        if (telemetry.diagnosticReason != null) {
            Spacer(modifier = Modifier.height(16.dp))
            VoiceGuardCard(containerColor = StatusWarning.copy(alpha = 0.1f), borderColor = StatusWarning) {
                Column(modifier = Modifier.fillMaxWidth()) {
                    Text("DIAGNOSTICS", style = MaterialTheme.typography.labelSmall, color = StatusWarning)
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = "Reason: ${telemetry.diagnosticReason}",
                        style = MaterialTheme.typography.bodySmall,
                        color = TextPrimary
                    )
                    if (telemetry.audioState == AudioCaptureState.CAPTURING || telemetry.audioState == AudioCaptureState.UNAVAILABLE) {
                        Text("Frames Captured: ${telemetry.framesCaptured}", style = MaterialTheme.typography.bodySmall, color = TextSecondary)
                        Text("Frames Sent: ${telemetry.framesSent}", style = MaterialTheme.typography.bodySmall, color = TextSecondary)
                        Text("Capture Mode: ${telemetry.captureMode}", style = MaterialTheme.typography.bodySmall, color = TextSecondary)
                    }
                }
            }
        }
        
        Spacer(modifier = Modifier.height(24.dp))
        
        if (telemetry.monitorState == MonitorState.ANALYZING) {
            SectionHeader("LIVE TELEMETRY")
            VoiceGuardCard {
                val riskColor = when (telemetry.alertLevel.uppercase()) {
                    "CRITICAL" -> StatusCritical
                    "HIGH" -> StatusWarning
                    "MODERATE" -> StatusWarning
                    else -> StatusOnline
                }
                
                if (!telemetry.hasValidResult) {
                    Box(modifier = Modifier.fillMaxWidth().padding(vertical = 24.dp), contentAlignment = Alignment.Center) {
                        Text(text = telemetry.alertLevel.replace("_", " "), style = MaterialTheme.typography.titleMedium, color = TextSecondary)
                    }
                } else {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.Top
                    ) {
                        MetricDisplay(
                            label = "CURRENT RISK SCORE",
                            value = String.format("%.3f", telemetry.currentRisk),
                            color = riskColor
                        )
                        StatusBadge(text = telemetry.alertLevel, color = riskColor)
                    }
                    
                    Spacer(modifier = Modifier.height(24.dp))
                    
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(4.dp)
                            .clip(RoundedCornerShape(2.dp))
                            .background(DividerColor)
                    ) {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth(if (telemetry.currentRisk > 0) telemetry.currentRisk.toFloat().coerceIn(0.05f, 1f) else 0.05f)
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
        
        if (telemetry.alertLevel == "CRITICAL" || telemetry.alertLevel == "HIGH") {
            Spacer(modifier = Modifier.height(24.dp))
            VoiceGuardCard(containerColor = StatusCritical.copy(alpha = 0.1f), borderColor = StatusCritical) {
                Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxWidth()) {
                    Text("⚠ POSSIBLE CLONED VOICE DETECTED", style = MaterialTheme.typography.titleMedium, color = StatusCritical)
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        "The caller's voice has shown strong synthetic characteristics over multiple analysis windows.\n\nDO NOT SHARE OTP / PIN / MONEY",
                        style = MaterialTheme.typography.bodySmall,
                        color = TextPrimary
                    )
                }
            }
        }
        } // end of else block
    }
}

@Composable
fun StatusRow(label: String, value: String, color: androidx.compose.ui.graphics.Color) {
    Column {
        Text(label, style = MaterialTheme.typography.labelSmall, color = TextTertiary)
        Spacer(modifier = Modifier.height(2.dp))
        Text(value, style = MaterialTheme.typography.bodyMedium, color = color)
    }
}
