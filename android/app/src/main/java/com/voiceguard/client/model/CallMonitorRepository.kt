package com.voiceguard.client.model

import android.content.Context
import com.voiceguard.client.network.ConnectionManager
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update

class CallMonitorRepository private constructor(context: Context) {
    
    val connectionManager = ConnectionManager(context.applicationContext)
    
    private val _telemetry = MutableStateFlow(CallMonitorTelemetry())
    val telemetry: StateFlow<CallMonitorTelemetry> = _telemetry

    fun updateTelemetry(updater: (CallMonitorTelemetry) -> CallMonitorTelemetry) {
        _telemetry.update(updater)
    }

    fun resetTelemetry() {
        _telemetry.value = CallMonitorTelemetry()
    }

    companion object {
        @Volatile
        private var instance: CallMonitorRepository? = null

        fun getInstance(context: Context): CallMonitorRepository {
            return instance ?: synchronized(this) {
                instance ?: CallMonitorRepository(context.applicationContext).also { instance = it }
            }
        }
    }
}
