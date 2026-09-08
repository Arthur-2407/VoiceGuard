package com.voiceguard.client.network

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.TimeUnit

enum class ConnectionState {
    DISCONNECTED, 
    NETWORK_UNAVAILABLE, 
    DISCOVERING, 
    DISCOVERY_TIMEOUT, 
    NODE_FOUND, 
    VALIDATING, 
    BACKEND_UNREACHABLE, 
    BACKEND_UNHEALTHY, 
    CONNECTED, 
    ERROR
}

class ConnectionManager(private val context: Context) {
    private val _connectionState = MutableStateFlow(ConnectionState.DISCONNECTED)
    val connectionState: StateFlow<ConnectionState> = _connectionState

    private val _serverUrl = MutableStateFlow<String?>(null)
    val serverUrl: StateFlow<String?> = _serverUrl

    private var nsdManager: NsdManager? = null
    private var discoveryListener: NsdManager.DiscoveryListener? = null
    
    private var connectivityManager: ConnectivityManager? = null
    private var networkCallback: ConnectivityManager.NetworkCallback? = null

    private val SERVICE_TYPE = "_voiceguard._tcp."
    
    private var discoveryJob: Job? = null
    private var isResolving = false

    val okHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()

    var api: VoiceGuardApi? = null
        private set

    init {
        connectivityManager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val request = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()

        networkCallback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                Log.d("ConnectionManager", "Network available")
                CoroutineScope(Dispatchers.Main).launch {
                    val currentState = _connectionState.value
                    if (currentState == ConnectionState.DISCONNECTED || currentState == ConnectionState.ERROR || currentState == ConnectionState.NETWORK_UNAVAILABLE) {
                        startDiscovery()
                    }
                }
            }

            override fun onLost(network: Network) {
                Log.d("ConnectionManager", "Network lost")
                CoroutineScope(Dispatchers.Main).launch {
                    _connectionState.value = ConnectionState.NETWORK_UNAVAILABLE
                    _serverUrl.value = null
                    api = null
                }
            }
        }
        try {
            connectivityManager?.registerNetworkCallback(request, networkCallback!!)
        } catch (e: Exception) {
            Log.e("ConnectionManager", "Failed to register network callback", e)
        }
    }

    fun startDiscovery() {
        val currentState = _connectionState.value
        if (currentState == ConnectionState.DISCOVERING || currentState == ConnectionState.CONNECTED || currentState == ConnectionState.NODE_FOUND || currentState == ConnectionState.VALIDATING) return

        val activeNetwork = connectivityManager?.activeNetwork
        val caps = connectivityManager?.getNetworkCapabilities(activeNetwork)
        val hasNetwork = caps != null && (caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) || caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) || caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR))
        
        if (!hasNetwork) {
            _connectionState.value = ConnectionState.NETWORK_UNAVAILABLE
            return
        }

        _connectionState.value = ConnectionState.DISCOVERING
        isResolving = false

        // Timeout mechanism
        discoveryJob?.cancel()
        discoveryJob = CoroutineScope(Dispatchers.Main).launch {
            delay(8000) // 8 seconds timeout
            if (_connectionState.value == ConnectionState.DISCOVERING) {
                Log.e("ConnectionManager", "Discovery timed out")
                _connectionState.value = ConnectionState.DISCOVERY_TIMEOUT
                stopDiscovery()
            }
        }

        nsdManager = context.getSystemService(Context.NSD_SERVICE) as NsdManager
        
        discoveryListener = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(regType: String) {
                Log.d("ConnectionManager", "Service discovery started")
            }

            override fun onServiceFound(service: NsdServiceInfo) {
                Log.d("ConnectionManager", "Service found: ${service.serviceName}")
                if (service.serviceType.contains("_voiceguard._tcp")) {
                    if (isResolving) return // Prevent concurrent resolution crashes
                    isResolving = true
                    
                    CoroutineScope(Dispatchers.Main).launch {
                        if (_connectionState.value == ConnectionState.DISCOVERING) {
                            _connectionState.value = ConnectionState.NODE_FOUND
                        }
                    }

                    try {
                        nsdManager?.resolveService(service, object : NsdManager.ResolveListener {
                            override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) {
                                Log.e("ConnectionManager", "Resolve failed: $errorCode")
                                isResolving = false
                            }

                            override fun onServiceResolved(serviceInfo: NsdServiceInfo) {
                                isResolving = false
                                val host = serviceInfo.host.hostAddress
                                val port = serviceInfo.port
                                Log.d("ConnectionManager", "Resolved service: $host:$port")
                                if (host != null) {
                                    CoroutineScope(Dispatchers.Main).launch {
                                        connectToServer(host, port)
                                    }
                                }
                            }
                        })
                    } catch (e: Exception) {
                        Log.e("ConnectionManager", "Exception during resolveService", e)
                        isResolving = false
                    }
                }
            }

            override fun onServiceLost(service: NsdServiceInfo) {
                Log.e("ConnectionManager", "Service lost: $service")
                if (_connectionState.value == ConnectionState.CONNECTED) {
                    _connectionState.value = ConnectionState.DISCONNECTED
                    _serverUrl.value = null
                    api = null
                }
            }

            override fun onDiscoveryStopped(serviceType: String) {
                Log.i("ConnectionManager", "Discovery stopped: $serviceType")
            }

            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.e("ConnectionManager", "Discovery failed: Error code:$errorCode")
                CoroutineScope(Dispatchers.Main).launch {
                    _connectionState.value = ConnectionState.ERROR
                }
                stopDiscovery()
            }

            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.e("ConnectionManager", "Stop discovery failed: Error code:$errorCode")
                stopDiscovery()
            }
        }
        
        try {
            nsdManager?.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, discoveryListener)
        } catch (e: Exception) {
            _connectionState.value = ConnectionState.ERROR
            Log.e("ConnectionManager", "Failed to start discovery", e)
        }
    }

    fun connectManually(host: String, port: Int) {
        stopDiscovery()
        connectToServer(host, port)
    }

    private fun connectToServer(host: String, port: Int) {
        if (_connectionState.value == ConnectionState.CONNECTED) return
        
        discoveryJob?.cancel()
        _connectionState.value = ConnectionState.VALIDATING
        
        val url = "http://$host:$port/"
        
        CoroutineScope(Dispatchers.IO).launch {
            try {
                // Real health check to the VoiceGuard API
                val httpUrl = URL("${url}health")
                val connection = httpUrl.openConnection() as HttpURLConnection
                connection.connectTimeout = 3000
                connection.readTimeout = 3000
                connection.requestMethod = "GET"
                connection.connect()
                
                val responseCode = connection.responseCode
                if (responseCode == 200) {
                    withContext(Dispatchers.Main) {
                        _serverUrl.value = url
                        val retrofit = Retrofit.Builder()
                            .baseUrl(url)
                            .client(okHttpClient)
                            .addConverterFactory(GsonConverterFactory.create())
                            .build()
                        
                        api = retrofit.create(VoiceGuardApi::class.java)
                        _connectionState.value = ConnectionState.CONNECTED
                        stopDiscovery() // Stop discovering once cleanly connected
                    }
                } else {
                    withContext(Dispatchers.Main) {
                        Log.e("ConnectionManager", "Health check failed with code $responseCode")
                        _connectionState.value = ConnectionState.BACKEND_UNHEALTHY
                    }
                }
                connection.disconnect()
            } catch (e: java.net.ConnectException) {
                Log.e("ConnectionManager", "Backend unreachable (Connection Refused)", e)
                withContext(Dispatchers.Main) {
                    _connectionState.value = ConnectionState.BACKEND_UNREACHABLE
                }
            } catch (e: java.net.SocketTimeoutException) {
                Log.e("ConnectionManager", "Backend unreachable (Timeout)", e)
                withContext(Dispatchers.Main) {
                    _connectionState.value = ConnectionState.BACKEND_UNREACHABLE
                }
            } catch (e: Exception) {
                Log.e("ConnectionManager", "Failed to connect to server", e)
                withContext(Dispatchers.Main) {
                    _connectionState.value = ConnectionState.ERROR
                }
            }
        }
    }

    fun stopDiscovery() {
        discoveryJob?.cancel()
        if (discoveryListener != null) {
            try {
                nsdManager?.stopServiceDiscovery(discoveryListener)
            } catch (e: Exception) {
                // Ignore if not started or already stopped
            }
            discoveryListener = null
        }
    }

    fun cleanup() {
        stopDiscovery()
        networkCallback?.let { 
            try {
                connectivityManager?.unregisterNetworkCallback(it)
            } catch (e: Exception) {}
        }
    }
}
