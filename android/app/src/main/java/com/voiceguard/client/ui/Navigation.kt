package com.voiceguard.client.ui

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import com.voiceguard.client.ui.screens.*

sealed class Screen(val route: String, val title: String, val icon: @Composable () -> Unit) {
    object Splash : Screen("splash", "Splash", { Icon(Icons.Default.Build, contentDescription = null) })
    object Dashboard : Screen("dashboard", "Home", { Icon(Icons.Default.Home, contentDescription = "Home") })
    object FileAnalysis : Screen("file_analysis", "Analysis", { Icon(Icons.Default.Search, contentDescription = "Analysis") })
    object LiveMonitor : Screen("live_monitor", "Monitor", { Icon(Icons.Default.PlayArrow, contentDescription = "Monitor") })
    object Speakers : Screen("speakers", "Speakers", { Icon(Icons.Default.Person, contentDescription = "Speakers") })
    object Alerts : Screen("alerts", "Alerts", { Icon(Icons.Default.Warning, contentDescription = "Alerts") })
}

val BottomNavScreens = listOf(
    Screen.Dashboard,
    Screen.LiveMonitor,
    Screen.FileAnalysis,
    Screen.Alerts,
    Screen.Speakers
)

@Composable
fun VoiceGuardNavHost(
    navController: NavHostController,
    viewModel: MainViewModel,
    modifier: Modifier = Modifier
) {
    NavHost(navController = navController, startDestination = Screen.Splash.route, modifier = modifier) {
        composable(Screen.Splash.route) { SplashScreen(navController, viewModel) }
        composable(Screen.Dashboard.route) { DashboardScreen(navController, viewModel) }
        composable(Screen.FileAnalysis.route) { FileAnalysisScreen(navController, viewModel) }
        composable(Screen.LiveMonitor.route) { LiveMonitorScreen(navController, viewModel) }
        composable(Screen.Speakers.route) { SpeakerManagementScreen(navController, viewModel) }
        composable(Screen.Alerts.route) { AlertHistoryScreen(navController, viewModel) }
    }
}
