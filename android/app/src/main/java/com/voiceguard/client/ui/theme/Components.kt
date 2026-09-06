package com.voiceguard.client.ui.theme

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

@Composable
fun VoiceGuardCard(
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit
) {
    val shape = RoundedCornerShape(12.dp)
    val border = BorderStroke(1.dp, DividerColor)
    
    if (onClick != null) {
        Surface(
            modifier = modifier,
            shape = shape,
            color = ElevatedSurface,
            border = border,
            onClick = onClick
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                content()
            }
        }
    } else {
        Surface(
            modifier = modifier,
            shape = shape,
            color = ElevatedSurface,
            border = border
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                content()
            }
        }
    }
}

@Composable
fun SectionHeader(title: String, modifier: Modifier = Modifier) {
    Text(
        text = title.uppercase(),
        style = MaterialTheme.typography.labelSmall,
        color = CyberBlue,
        modifier = modifier.padding(bottom = 8.dp, top = 16.dp)
    )
}

@Composable
fun StatusBadge(text: String, color: Color, modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(4.dp),
        color = color.copy(alpha = 0.15f),
        border = BorderStroke(1.dp, color.copy(alpha = 0.5f))
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier
                    .size(6.dp)
                    .background(color, RoundedCornerShape(3.dp))
            )
            Spacer(modifier = Modifier.width(6.dp))
            Text(
                text = text.uppercase(),
                style = MaterialTheme.typography.labelSmall,
                color = color
            )
        }
    }
}

@Composable
fun MetricDisplay(label: String, value: String, color: Color = TextPrimary, modifier: Modifier = Modifier) {
    Column(modifier = modifier) {
        Text(text = label.uppercase(), style = MaterialTheme.typography.labelSmall, color = TextTertiary)
        Spacer(modifier = Modifier.height(4.dp))
        Text(text = value, style = MaterialTheme.typography.displaySmall, color = color)
    }
}
