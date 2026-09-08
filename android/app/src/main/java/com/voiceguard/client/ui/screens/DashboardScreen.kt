package com.voiceguard.client.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material.icons.filled.Call
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.voiceguard.client.network.ConnectionState
import com.voiceguard.client.ui.MainViewModel
import com.voiceguard.client.ui.Screen
import com.voiceguard.client.ui.theme.*

@Composable
fun DashboardScreen(navController: NavController, viewModel: MainViewModel) {
    val state by viewModel.connectionState.collectAsState()
    val serverUrl by viewModel.serverUrl.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp)
    ) {
        // HERO AREA
        Text("VOICEGUARD", style = MaterialTheme.typography.headlineMedium, color = TextPrimary)
        Text("AI SECURITY CORE", style = MaterialTheme.typography.labelSmall, color = CyberBlue)
        
        Spacer(modifier = Modifier.height(32.dp))
        
        // SYSTEM STATUS
        SectionHeader("SYSTEM STATE")
        VoiceGuardCard {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Text("CORE CONNECTION", style = MaterialTheme.typography.titleMedium, color = TextPrimary)
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = if (state == ConnectionState.CONNECTED) "Connected via Local Network" else "Connection Disconnected",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextSecondary
                    )
                    if (serverUrl != null && state == ConnectionState.CONNECTED) {
                        Spacer(modifier = Modifier.height(8.dp))
                        Text("ENDPOINT: $serverUrl", style = MaterialTheme.typography.labelSmall, color = TextTertiary)
                    }
                }
                StatusBadge(
                    text = if (state == ConnectionState.CONNECTED) "ONLINE" else "OFFLINE",
                    color = if (state == ConnectionState.CONNECTED) StatusOnline else StatusCritical
                )
            }
        }
        
        Spacer(modifier = Modifier.height(24.dp))
        
        // COMMAND CENTER ACTIONS
        SectionHeader("COMMAND CENTER")
        
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            VoiceGuardCard(
                modifier = Modifier.weight(1f),
                onClick = { navController.navigate(Screen.FileAnalysis.route) }
            ) {
                Icon(Icons.Default.Search, contentDescription = null, tint = CyberBlue, modifier = Modifier.size(32.dp))
                Spacer(modifier = Modifier.height(16.dp))
                Text("FILE ANALYSIS", style = MaterialTheme.typography.labelSmall, color = TextPrimary)
                Text("Inspect audio media", style = MaterialTheme.typography.bodyMedium, color = TextSecondary, modifier = Modifier.padding(top = 4.dp))
            }
            
            VoiceGuardCard(
                modifier = Modifier.weight(1f),
                onClick = { navController.navigate(Screen.LiveMonitor.route) }
            ) {
                Icon(Icons.Default.PlayArrow, contentDescription = null, tint = StatusWarning, modifier = Modifier.size(32.dp))
                Spacer(modifier = Modifier.height(16.dp))
                Text("LIVE MONITOR", style = MaterialTheme.typography.labelSmall, color = TextPrimary)
                Text("Room telemetry", style = MaterialTheme.typography.bodyMedium, color = TextSecondary, modifier = Modifier.padding(top = 4.dp))
            }
        }
        
        Spacer(modifier = Modifier.height(16.dp))
        
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            VoiceGuardCard(
                modifier = Modifier.fillMaxWidth(),
                onClick = { navController.navigate(Screen.CallMonitor.route) }
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Default.Call, contentDescription = null, tint = StatusOnline, modifier = Modifier.size(32.dp))
                    Spacer(modifier = Modifier.width(16.dp))
                    Column {
                        Text("CALL SECURITY", style = MaterialTheme.typography.labelSmall, color = TextPrimary)
                        Text("Remote caller deepfake monitoring", style = MaterialTheme.typography.bodyMedium, color = TextSecondary, modifier = Modifier.padding(top = 4.dp))
                    }
                }
            }
        }
        
        Spacer(modifier = Modifier.height(16.dp))
        
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            VoiceGuardCard(
                modifier = Modifier.weight(1f),
                onClick = { navController.navigate(Screen.Speakers.route) }
            ) {
                Icon(Icons.Default.Person, contentDescription = null, tint = ElectricCyan, modifier = Modifier.size(32.dp))
                Spacer(modifier = Modifier.height(16.dp))
                Text("SPEAKERS", style = MaterialTheme.typography.labelSmall, color = TextPrimary)
                Text("Trusted profiles", style = MaterialTheme.typography.bodyMedium, color = TextSecondary, modifier = Modifier.padding(top = 4.dp))
            }
            
            VoiceGuardCard(
                modifier = Modifier.weight(1f),
                onClick = { navController.navigate(Screen.Alerts.route) }
            ) {
                Icon(Icons.Default.Warning, contentDescription = null, tint = StatusCritical, modifier = Modifier.size(32.dp))
                Spacer(modifier = Modifier.height(16.dp))
                Text("INCIDENTS", style = MaterialTheme.typography.labelSmall, color = TextPrimary)
                Text("Security timeline", style = MaterialTheme.typography.bodyMedium, color = TextSecondary, modifier = Modifier.padding(top = 4.dp))
            }
        }
    }
}
