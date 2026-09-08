package com.voiceguard.client.model

enum class TelephonyCallState { IDLE, RINGING, ACTIVE, UNKNOWN }
enum class MonitorState { IDLE, INITIALIZING, STREAMING, ANALYZING, UNAVAILABLE }
enum class AudioCaptureState { IDLE, INITIALIZING, CAPTURING, UNAVAILABLE }
enum class BackendState { DISCONNECTED, CONNECTING, CONNECTED, ERROR }
enum class DetectorState { IDLE, READY, UNAVAILABLE }

data class CallMonitorTelemetry(
    val callState: TelephonyCallState = TelephonyCallState.IDLE,
    val monitorState: MonitorState = MonitorState.IDLE,
    val audioState: AudioCaptureState = AudioCaptureState.IDLE,
    val backendState: BackendState = BackendState.DISCONNECTED,
    val detectorState: DetectorState = DetectorState.IDLE,
    val audioSource: String = "NONE",
    val captureMode: String = "NONE",
    val diagnosticReason: String? = null,
    val framesCaptured: Long = 0,
    val framesSent: Long = 0,
    val currentRisk: Double = 0.0,
    val alertLevel: String = "ANALYZING...",
    val hasValidResult: Boolean = false,
    val resultAgeMs: Long = 0,
    val lastResultTimestamp: Long = 0
)
