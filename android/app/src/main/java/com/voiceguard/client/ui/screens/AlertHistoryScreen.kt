package com.voiceguard.client.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.voiceguard.client.network.Alert
import com.voiceguard.client.ui.MainViewModel
import com.voiceguard.client.ui.theme.*
import kotlinx.coroutines.launch

@Composable
fun AlertHistoryScreen(navController: NavController, viewModel: MainViewModel) {
    val coroutineScope = rememberCoroutineScope()
    var alerts by remember { mutableStateOf<List<Alert>>(emptyList()) }
    var isLoading by remember { mutableStateOf(true) }
    var errorMessage by remember { mutableStateOf<String?>(null) }
    var refreshTrigger by remember { mutableStateOf(0) }

    LaunchedEffect(refreshTrigger) {
        coroutineScope.launch {
            try {
                isLoading = true
                val api = viewModel.connectionManager.api
                if (api != null) {
                    alerts = api.getRecentAlerts(50).alerts
                } else {
                    errorMessage = "CORE CONNECTION OFFLINE"
                }
            } catch (e: Exception) {
                errorMessage = e.message ?: "FAILED TO RETRIEVE INCIDENTS"
            } finally {
                isLoading = false
            }
        }
    }

    Column(modifier = Modifier.fillMaxSize().padding(24.dp)) {
        Text("INCIDENT LOG", style = MaterialTheme.typography.headlineMedium, color = TextPrimary)
        Text("SECURITY EVENT TIMELINE", style = MaterialTheme.typography.labelSmall, color = CyberBlue)
        
        Spacer(modifier = Modifier.height(32.dp))
        
        if (isLoading) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = CyberBlue)
            }
        } else if (errorMessage != null) {
            VoiceGuardCard {
                Text("SYSTEM ERROR", style = MaterialTheme.typography.labelSmall, color = StatusCritical)
                Spacer(modifier = Modifier.height(8.dp))
                Text(errorMessage!!, style = MaterialTheme.typography.bodyMedium, color = TextPrimary)
                Spacer(modifier = Modifier.height(16.dp))
                Button(
                    onClick = { refreshTrigger++ },
                    colors = ButtonDefaults.buttonColors(containerColor = CyberBlue)
                ) {
                    Text("RETRY", style = MaterialTheme.typography.labelSmall, color = DeepSpaceBackground)
                }
            }
        } else if (alerts.isEmpty()) {
            VoiceGuardCard {
                Text("NO SECURITY INCIDENTS DETECTED", style = MaterialTheme.typography.labelSmall, color = StatusOnline)
            }
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                items(alerts) { alert ->
                    VoiceGuardCard {
                        val riskColor = when (alert.alertLevel.uppercase()) {
                            "CRITICAL" -> StatusCritical
                            "HIGH" -> StatusWarning
                            "MODERATE" -> StatusWarning
                            else -> StatusOnline
                        }
                        
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            StatusBadge(text = alert.alertLevel, color = riskColor)
                            Text(alert.timestamp.toString(), style = MaterialTheme.typography.labelSmall, color = TextTertiary)
                        }
                        
                        Divider(color = DividerColor, modifier = Modifier.padding(vertical = 12.dp))
                        
                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            MetricDisplay("RISK SCORE", String.format("%.3f", alert.riskScore), riskColor)
                            if (alert.speakerId != null) {
                                MetricDisplay("TARGET ID", alert.speakerId, TextPrimary)
                            }
                        }
                    }
                }
            }
        }
    }
}
