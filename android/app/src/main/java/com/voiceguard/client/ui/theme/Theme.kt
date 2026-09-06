package com.voiceguard.client.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable

private val DarkColorScheme = darkColorScheme(
    primary = CyberBlue,
    secondary = ElectricCyan,
    tertiary = MutedSlate,
    background = DeepSpaceBackground,
    surface = ElevatedSurface,
    surfaceVariant = HighlightSurface,
    onPrimary = TextPrimary,
    onSecondary = DeepSpaceBackground,
    onBackground = TextPrimary,
    onSurface = TextPrimary,
    onSurfaceVariant = TextSecondary,
    error = StatusCritical,
    outline = DividerColor
)

@Composable
fun VoiceGuardClientTheme(
    content: @Composable () -> Unit
) {
    MaterialTheme(
        colorScheme = DarkColorScheme,
        typography = Typography,
        content = content
    )
}
