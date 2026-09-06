package com.voiceguard.client.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.voiceguard.client.network.ConnectionManager
import com.voiceguard.client.network.ConnectionState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class MainViewModel(application: Application) : AndroidViewModel(application) {
    
    val connectionManager = ConnectionManager(application)
    
    val connectionState: StateFlow<ConnectionState> = connectionManager.connectionState
    val serverUrl: StateFlow<String?> = connectionManager.serverUrl
    
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
        connectionManager.cleanup()
    }
}
