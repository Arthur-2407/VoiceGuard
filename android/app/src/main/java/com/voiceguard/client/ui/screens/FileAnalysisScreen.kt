package com.voiceguard.client.ui.screens

import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.voiceguard.client.network.AnalysisResponse
import com.voiceguard.client.ui.MainViewModel
import com.voiceguard.client.ui.theme.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody
import java.io.File
import java.io.FileOutputStream

@Composable
fun FileAnalysisScreen(navController: NavController, viewModel: MainViewModel) {
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    
    var selectedUri by remember { mutableStateOf<Uri?>(null) }
    var fileName by remember { mutableStateOf("") }
    var isAnalyzing by remember { mutableStateOf(false) }
    var analysisResult by remember { mutableStateOf<AnalysisResponse?>(null) }
    var errorMessage by remember { mutableStateOf<String?>(null) }
    
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
        selectedUri = uri
        uri?.let {
            val cursor = context.contentResolver.query(it, null, null, null, null)
            cursor?.use { c ->
                val nameIndex = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (c.moveToFirst() && nameIndex >= 0) {
                    fileName = c.getString(nameIndex)
                }
            }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp)
    ) {
        Text("FILE ANALYSIS", style = MaterialTheme.typography.headlineMedium, color = TextPrimary)
        Text("BATCH MEDIA INSPECTION", style = MaterialTheme.typography.labelSmall, color = CyberBlue)
        
        Spacer(modifier = Modifier.height(32.dp))
        
        SectionHeader("INPUT SOURCE")
        VoiceGuardCard {
            if (fileName.isEmpty()) {
                Column(
                    modifier = Modifier.fillMaxWidth().padding(16.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Icon(Icons.Default.Add, contentDescription = null, tint = TextTertiary, modifier = Modifier.size(32.dp))
                    Spacer(modifier = Modifier.height(8.dp))
                    Text("NO MEDIA SELECTED", style = MaterialTheme.typography.labelSmall, color = TextTertiary)
                }
            } else {
                Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Default.Search, contentDescription = null, tint = CyberBlue)
                    Spacer(modifier = Modifier.width(16.dp))
                    Column {
                        Text("TARGET MEDIA", style = MaterialTheme.typography.labelSmall, color = TextTertiary)
                        Text(fileName, style = MaterialTheme.typography.bodyMedium, color = TextPrimary)
                    }
                }
            }
            
            Spacer(modifier = Modifier.height(16.dp))
            OutlinedButton(
                onClick = { launcher.launch("audio/*") },
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = CyberBlue),
                border = BorderStroke(1.dp, CyberBlue)
            ) {
                Text(if (fileName.isEmpty()) "SELECT AUDIO SOURCE" else "CHANGE SOURCE", style = MaterialTheme.typography.labelSmall)
            }
        }
        
        Spacer(modifier = Modifier.height(24.dp))
        
        if (errorMessage != null) {
            Text("ERROR: $errorMessage", color = StatusCritical, style = MaterialTheme.typography.labelSmall)
            Spacer(modifier = Modifier.height(16.dp))
        }
        
        Button(
            onClick = {
                if (selectedUri != null && viewModel.connectionManager.api != null) {
                    isAnalyzing = true
                    errorMessage = null
                    analysisResult = null
                    
                    coroutineScope.launch {
                        try {
                            val tempFile = File(context.cacheDir, fileName.ifEmpty { "upload.tmp" })
                            withContext(Dispatchers.IO) {
                                context.contentResolver.openInputStream(selectedUri!!)?.use { input ->
                                    FileOutputStream(tempFile).use { output ->
                                        input.copyTo(output)
                                    }
                                }
                            }
                            
                            val requestFile = tempFile.asRequestBody("audio/*".toMediaTypeOrNull())
                            val body = MultipartBody.Part.createFormData("file", tempFile.name, requestFile)
                            
                            val api = viewModel.connectionManager.api
                            if (api == null) {
                                errorMessage = "API NO LONGER CONNECTED"
                            } else {
                                analysisResult = api.analyzeAudio(body)
                            }
                        } catch (e: Exception) {
                            errorMessage = e.message ?: "ANALYSIS PIPELINE FAILURE"
                        } finally {
                            isAnalyzing = false
                        }
                    }
                }
            },
            enabled = selectedUri != null && !isAnalyzing,
            modifier = Modifier.fillMaxWidth().height(56.dp),
            colors = ButtonDefaults.buttonColors(containerColor = CyberBlue, contentColor = DeepSpaceBackground)
        ) {
            if (isAnalyzing) {
                CircularProgressIndicator(modifier = Modifier.size(24.dp), color = DeepSpaceBackground, strokeWidth = 2.dp)
                Spacer(modifier = Modifier.width(16.dp))
                Text("ANALYZING TARGET...", style = MaterialTheme.typography.labelSmall)
            } else {
                Text("INITIATE ANALYSIS", style = MaterialTheme.typography.labelSmall)
            }
        }
        
        Spacer(modifier = Modifier.height(32.dp))
        
        analysisResult?.let { res ->
            SectionHeader("ANALYSIS RESULTS")
            VoiceGuardCard {
                val riskColor = when (res.alertLevel.uppercase()) {
                    "CRITICAL" -> StatusCritical
                    "HIGH" -> StatusWarning
                    "MODERATE" -> StatusWarning
                    else -> StatusOnline
                }
                
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text("RISK CLASSIFICATION", style = MaterialTheme.typography.labelSmall, color = TextTertiary)
                    StatusBadge(text = res.alertLevel, color = riskColor)
                }
                
                Divider(color = DividerColor, modifier = Modifier.padding(vertical = 16.dp))
                
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    MetricDisplay("PEAK RISK", String.format("%.3f", res.peakRisk), riskColor, modifier = Modifier.weight(1f))
                    MetricDisplay("MEAN RISK", String.format("%.3f", res.meanRisk), TextPrimary, modifier = Modifier.weight(1f))
                    MetricDisplay("CHUNKS", res.totalChunks.toString(), TextPrimary, modifier = Modifier.weight(1f))
                }
                
                Divider(color = DividerColor, modifier = Modifier.padding(vertical = 16.dp))
                
                Text(res.recommendation.title.uppercase(), style = MaterialTheme.typography.labelSmall, color = CyberBlue)
                Spacer(modifier = Modifier.height(4.dp))
                Text(res.recommendation.message, style = MaterialTheme.typography.bodyMedium, color = TextSecondary)
            }
        }
    }
}
