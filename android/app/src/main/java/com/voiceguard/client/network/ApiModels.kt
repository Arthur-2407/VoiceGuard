package com.voiceguard.client.network

import com.google.gson.annotations.SerializedName

data class HealthResponse(
    val status: String,
    val service: String,
    val version: String
)

data class Recommendation(
    val title: String,
    val message: String,
    val actions: List<String>,
    val color: String
)

data class ChunkScore(
    @SerializedName("chunk_id") val chunkId: Int,
    @SerializedName("detection_score") val detectionScore: Float,
    @SerializedName("risk_score") val riskScore: Float,
    @SerializedName("alert_level") val alertLevel: String,
    @SerializedName("processing_ms") val processingMs: Float
)

data class AnalysisResponse(
    @SerializedName("session_id") val sessionId: String,
    val filename: String,
    @SerializedName("total_chunks") val totalChunks: Int,
    @SerializedName("peak_risk") val peakRisk: Float,
    @SerializedName("mean_risk") val meanRisk: Float,
    @SerializedName("final_risk") val finalRisk: Float,
    @SerializedName("alert_level") val alertLevel: String,
    val recommendation: Recommendation,
    @SerializedName("chunk_scores") val chunkScores: List<ChunkScore>,
    @SerializedName("processing_time_ms") val processingTimeMs: Float
)

data class SpeakerInfo(
    @SerializedName("speaker_id") val speakerId: String,
    val name: String,
    val organization: String?,
    val role: String?,
    @SerializedName("num_samples") val numSamples: Int,
    @SerializedName("created_at") val createdAt: String?
)

data class EnrollResponse(
    @SerializedName("speaker_id") val speakerId: String,
    val name: String,
    @SerializedName("num_samples") val numSamples: Int,
    val message: String
)

data class Alert(
    @SerializedName("session_id") val sessionId: String?,
    @SerializedName("chunk_id") val chunkId: Int?,
    val timestamp: Double,
    @SerializedName("risk_score") val riskScore: Float,
    @SerializedName("alert_level") val alertLevel: String,
    @SerializedName("recommendation_title") val recommendationTitle: String?,
    @SerializedName("recommendation_message") val recommendationMessage: String?,
    @SerializedName("speaker_id") val speakerId: String?
)

data class AlertHistoryResponse(
    val alerts: List<Alert>
)

data class ThresholdConfig(
    val low: Float,
    val medium: Float,
    val high: Float
)

data class StatusResponse(
    val status: String,
    @SerializedName("detector_initialized") val detectorInitialized: Boolean,
    @SerializedName("connected_clients") val connectedClients: Int
)
