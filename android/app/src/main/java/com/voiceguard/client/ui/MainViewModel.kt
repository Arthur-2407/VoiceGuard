package com.voiceguard.client.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import com.voiceguard.client.model.CallMonitorRepository
import com.voiceguard.client.network.ConnectionState
import kotlinx.coroutines.flow.StateFlow

class MainViewModel(application: Application) : AndroidViewModel(application) {
    
    private val repository = CallMonitorRepository.getInstance(application)
    val connectionManager = repository.connectionManager
    
    val connectionState: StateFlow<ConnectionState> = connectionManager.connectionState
    val serverUrl: StateFlow<String?> = connectionManager.serverUrl
    
    val telemetry = repository.telemetry
    
    init {
        // Start automatic discovery on init
        connectionManager.startDiscovery()
    }
    
    fun connectManually(host: String, port: String) {
        val p = port.toIntOrNull() ?: 8000
        connectionManager.connectManually(host, p)
    }
    
    fun retryDiscovery() {
        connectionManager.startDiscovery()
    }
    
    override fun onCleared() {
        super.onCleared()
        // Do not cleanup app-wide ConnectionManager here
    }
}
