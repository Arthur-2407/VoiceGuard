package com.voiceguard.client.ui.screens

import androidx.compose.animation.core.*
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.voiceguard.client.network.ConnectionState
import com.voiceguard.client.ui.MainViewModel
import com.voiceguard.client.ui.Screen
import com.voiceguard.client.ui.theme.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SplashScreen(navController: NavController, viewModel: MainViewModel) {
    val state by viewModel.connectionState.collectAsState()
    
    LaunchedEffect(state) {
        if (state == ConnectionState.CONNECTED) {
            navController.navigate(Screen.Dashboard.route) {
                popUpTo(Screen.Splash.route) { inclusive = true }
            }
        }
    }

    // A pulsing animation for the loading state
    val transition = rememberInfiniteTransition(label = "pulse")
    val alpha by transition.animateFloat(
        initialValue = 0.3f,
        targetValue = 1.0f,
        animationSpec = infiniteRepeatable(
            animation = tween(1000, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "pulseAlpha"
    )

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(DeepSpaceBackground)
            .padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(
            text = "VOICEGUARD",
            style = MaterialTheme.typography.displayLarge,
            color = TextPrimary
        )
        Text(
            text = "AI SECURITY CORE // INITIALIZATION",
            style = MaterialTheme.typography.labelSmall,
            color = CyberBlue
        )
        
        Spacer(modifier = Modifier.height(48.dp))
        
        when (state) {
            ConnectionState.DISCOVERING, ConnectionState.CONNECTING -> {
                Box(
                    modifier = Modifier
                        .size(64.dp)
                        .clip(RoundedCornerShape(8.dp))
                        .border(1.dp, CyberBlue.copy(alpha = alpha), RoundedCornerShape(8.dp))
                        .background(CyberBlue.copy(alpha = alpha * 0.2f)),
                    contentAlignment = Alignment.Center
                ) {
                    CircularProgressIndicator(
                        color = CyberBlue,
                        strokeWidth = 2.dp,
                        modifier = Modifier.size(32.dp)
                    )
                }
                Spacer(modifier = Modifier.height(24.dp))
                Text(
                    text = if (state == ConnectionState.DISCOVERING) "SCANNING LOCAL NETWORK..." else "ESTABLISHING SECURE UPLINK...",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextSecondary
                )
            }
            ConnectionState.ERROR, ConnectionState.DISCONNECTED -> {
                Icon(
                    imageVector = Icons.Default.Warning,
                    contentDescription = "Connection Failed",
                    tint = StatusWarning,
                    modifier = Modifier.size(48.dp)
                )
                Spacer(modifier = Modifier.height(16.dp))
                Text(
                    text = "NODE DISCOVERY FAILED",
                    style = MaterialTheme.typography.titleMedium,
                    color = StatusWarning
                )
                Text(
                    text = "Ensure VoiceGuard PC is running and accessible on the local network.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = TextSecondary,
                    modifier = Modifier.padding(top = 8.dp, bottom = 32.dp)
                )
                
                var ip by remember { mutableStateOf("") }
                var port by remember { mutableStateOf("8000") }
                
                OutlinedTextField(
                    value = ip,
                    onValueChange = { ip = it },
                    label = { Text("MANUAL HOST IP", style = MaterialTheme.typography.labelSmall) },
                    placeholder = { Text("e.g. 192.168.1.50") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    colors = TextFieldDefaults.outlinedTextFieldColors(
                        focusedBorderColor = CyberBlue,
                        unfocusedBorderColor = DividerColor,
                        cursorColor = CyberBlue
                    )
                )
                Spacer(modifier = Modifier.height(8.dp))
                OutlinedTextField(
                    value = port,
                    onValueChange = { port = it },
                    label = { Text("PORT", style = MaterialTheme.typography.labelSmall) },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    colors = TextFieldDefaults.outlinedTextFieldColors(
                        focusedBorderColor = CyberBlue,
                        unfocusedBorderColor = DividerColor
                    )
                )
                Spacer(modifier = Modifier.height(24.dp))
                
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    OutlinedButton(
                        onClick = { viewModel.retryDiscovery() },
                        modifier = Modifier.weight(1f),
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = CyberBlue),
                        border = BorderStroke(1.dp, CyberBlue)
                    ) {
                        Text("RETRY AUTO", style = MaterialTheme.typography.labelSmall)
                    }
                    Button(
                        onClick = { viewModel.connectManually(ip, port) },
                        modifier = Modifier.weight(1f),
                        colors = ButtonDefaults.buttonColors(containerColor = CyberBlue, contentColor = DeepSpaceBackground),
                        enabled = ip.isNotBlank()
                    ) {
                        Text("CONNECT", style = MaterialTheme.typography.labelSmall)
                    }
                }
            }
            else -> {}
        }
    }
}
