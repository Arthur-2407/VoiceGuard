package com.voiceguard.client

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.*
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.voiceguard.client.ui.BottomNavScreens
import com.voiceguard.client.ui.MainViewModel
import com.voiceguard.client.ui.Screen
import com.voiceguard.client.ui.VoiceGuardNavHost
import com.voiceguard.client.ui.theme.VoiceGuardClientTheme

class MainActivity : ComponentActivity() {
    private val viewModel: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            VoiceGuardClientTheme {
                val navController = rememberNavController()
                val navBackStackEntry by navController.currentBackStackEntryAsState()
                val currentRoute = navBackStackEntry?.destination?.route
                
                // Hide bottom nav on splash screen
                val showBottomNav = currentRoute != Screen.Splash.route

                Scaffold(
                    bottomBar = {
                        if (showBottomNav) {
                            NavigationBar {
                                BottomNavScreens.forEach { screen ->
                                    NavigationBarItem(
                                        icon = screen.icon,
                                        label = { Text(screen.title) },
                                        selected = currentRoute == screen.route,
                                        onClick = {
                                            if (currentRoute != screen.route) {
                                                navController.navigate(screen.route) {
                                                    popUpTo(Screen.Dashboard.route) {
                                                        saveState = true
                                                    }
                                                    launchSingleTop = true
                                                    restoreState = true
                                                }
                                            }
                                        }
                                    )
                                }
                            }
                        }
                    }
                ) { innerPadding ->
                    Surface(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(innerPadding),
                        color = MaterialTheme.colorScheme.background
                    ) {
                        VoiceGuardNavHost(navController = navController, viewModel = viewModel)
                    }
                }
            }
        }
    }
}
