package com.voiceguard.client.network

import okhttp3.MultipartBody
import okhttp3.RequestBody
import retrofit2.http.*

interface VoiceGuardApi {

    @GET("health")
    suspend fun getHealth(): HealthResponse

    @Multipart
    @POST("api/analyze")
    suspend fun analyzeAudio(
        @Part file: MultipartBody.Part,
        @Part("speaker_id") speakerId: RequestBody? = null
    ): AnalysisResponse

    @Multipart
    @POST("api/speakers/enroll")
    suspend fun enrollSpeaker(
        @Part("name") name: RequestBody,
        @Part files: List<MultipartBody.Part>,
        @Part("speaker_id") speakerId: RequestBody? = null,
        @Part("organization") organization: RequestBody? = null,
        @Part("role") role: RequestBody? = null
    ): EnrollResponse

    @GET("api/speakers")
    suspend fun listSpeakers(): List<SpeakerInfo>

    @DELETE("api/speakers/{id}")
    suspend fun deleteSpeaker(@Path("id") speakerId: String)

    @GET("api/alerts/recent")
    suspend fun getRecentAlerts(@Query("limit") limit: Int = 50): AlertHistoryResponse

    @GET("api/config/status")
    suspend fun getStatus(): StatusResponse
}
