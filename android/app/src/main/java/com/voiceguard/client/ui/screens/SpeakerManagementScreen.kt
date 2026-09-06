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
import com.voiceguard.client.network.SpeakerInfo
import com.voiceguard.client.ui.MainViewModel
import com.voiceguard.client.ui.theme.*
import kotlinx.coroutines.launch

@Composable
fun SpeakerManagementScreen(navController: NavController, viewModel: MainViewModel) {
    val coroutineScope = rememberCoroutineScope()
    var speakers by remember { mutableStateOf<List<SpeakerInfo>>(emptyList()) }
    var isLoading by remember { mutableStateOf(true) }
    var errorMessage by remember { mutableStateOf<String?>(null) }
    var refreshTrigger by remember { mutableStateOf(0) }

    LaunchedEffect(refreshTrigger) {
        coroutineScope.launch {
            try {
                isLoading = true
                val api = viewModel.connectionManager.api
                if (api != null) {
                    speakers = api.listSpeakers()
                } else {
                    errorMessage = "CORE CONNECTION OFFLINE"
                }
            } catch (e: Exception) {
                errorMessage = e.message ?: "FAILED TO RETRIEVE IDENTITIES"
            } finally {
                isLoading = false
            }
        }
    }

    Column(modifier = Modifier.fillMaxSize().padding(24.dp)) {
        Text("SPEAKER PROFILES", style = MaterialTheme.typography.headlineMedium, color = TextPrimary)
        Text("TRUSTED IDENTITY REGISTRY", style = MaterialTheme.typography.labelSmall, color = CyberBlue)
        
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
        } else if (speakers.isEmpty()) {
            VoiceGuardCard {
                Text("NO PROFILES REGISTERED", style = MaterialTheme.typography.labelSmall, color = TextTertiary)
            }
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                items(speakers) { speaker ->
                    VoiceGuardCard {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(speaker.name.uppercase(), style = MaterialTheme.typography.titleMedium, color = TextPrimary)
                                Spacer(modifier = Modifier.height(4.dp))
                                Text("ID: ${speaker.speakerId}", style = MaterialTheme.typography.labelSmall, color = TextTertiary)
                                Spacer(modifier = Modifier.height(8.dp))
                                StatusBadge(text = "${speaker.numSamples} SAMPLES", color = CyberBlue)
                            }
                            OutlinedButton(
                                onClick = {
                                    coroutineScope.launch {
                                        try {
                                            viewModel.connectionManager.api?.deleteSpeaker(speaker.speakerId)
                                            refreshTrigger++
                                        } catch (e: Exception) {
                                            errorMessage = e.message ?: "DELETION FAILED"
                                        }
                                    }
                                },
                                colors = ButtonDefaults.outlinedButtonColors(contentColor = StatusCritical)
                            ) {
                                Text("REVOKE", style = MaterialTheme.typography.labelSmall)
                            }
                        }
                    }
                }
            }
        }
    }
}
