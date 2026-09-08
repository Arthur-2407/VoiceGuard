package com.voiceguard.client.audio

import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.delay

enum class AudioSourceType {
    MIC,
    VOICE_COMMUNICATION // Acoustic fallback for calls
}

class RealTimeAudioPipeline(
    private val sourceType: AudioSourceType,
    private val onAudioData: (ByteArray) -> Unit,
    private val onError: (String) -> Unit = {}
) {
    private var audioRecord: AudioRecord? = null
    private var isRecording = false
    private var recordingJob: Job? = null
    
    var framesCaptured: Long = 0
        private set

    fun start() {
        if (isRecording) return

        val source = when (sourceType) {
            AudioSourceType.MIC -> MediaRecorder.AudioSource.MIC
            AudioSourceType.VOICE_COMMUNICATION -> MediaRecorder.AudioSource.VOICE_COMMUNICATION
        }

        try {
            val bufferSize = AudioRecord.getMinBufferSize(
                16000,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT
            )
            if (bufferSize <= 0) throw IllegalStateException("Invalid buffer size")

            audioRecord = AudioRecord(
                source,
                16000,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                bufferSize * 2
            )

            if (audioRecord?.state != AudioRecord.STATE_INITIALIZED) {
                throw IllegalStateException("AudioRecord initialization failed (state = ${audioRecord?.state}). Possibly restricted by system policy during call.")
            }

            audioRecord?.startRecording()
            if (audioRecord?.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
                throw IllegalStateException("AudioRecord failed to start recording.")
            }
            isRecording = true
            framesCaptured = 0
        } catch (e: SecurityException) {
            isRecording = false
            throw e
        } catch (e: Exception) {
            isRecording = false
            throw e
        }
    }

    suspend fun streamData() = coroutineScope {
        recordingJob = launch(Dispatchers.IO) {
            val bufferSize = AudioRecord.getMinBufferSize(
                16000,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT
            )
            val buffer = ByteArray(bufferSize)
            var zeroByteCount = 0
            val zeroByteThreshold = 50 // roughly 1 second of consecutive 0-byte reads
            
            while (isActive && isRecording) {
                val tCapture = System.nanoTime()
                val read = audioRecord?.read(buffer, 0, buffer.size) ?: 0
                val tReady = System.nanoTime()
                
                if (read > 0) {
                    zeroByteCount = 0
                    framesCaptured++
                    onAudioData(buffer.copyOf(read))
                } else {
                    zeroByteCount++
                    if (zeroByteCount > zeroByteThreshold) {
                        Log.e("RealTimeAudioPipeline", "Consecutive zero or negative reads. Capture failed.")
                        onError("Audio source unavailable (read $read bytes). Hardware blocked?")
                        break
                    }
                    delay(20) // prevent tight loop if read returns 0 instantly
                }
                
                val tSend = System.nanoTime()
                val capToReady = (tReady - tCapture) / 1_000_000.0
                val readyToSend = (tSend - tReady) / 1_000_000.0
                Log.d("VoiceGuardLatency", "Audio Chunk [size=$read]: capture->ready=${capToReady}ms, ready->send=${readyToSend}ms")
            }
        }
    }

    fun stop() {
        isRecording = false
        recordingJob?.cancel()
        recordingJob = null
        try {
            audioRecord?.stop()
        } catch (e: Exception) {}
        audioRecord?.release()
        audioRecord = null
    }
}
