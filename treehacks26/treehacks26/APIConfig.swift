//
//  APIConfig.swift
//  treehacks26
//

import Foundation

/// Base URL for the FastAPI backend.
enum APIConfig {
    /// Use "http://localhost:8000" for local dev, "https://treehacks.tzhu.dev" for tunnel.
    static let baseURL = "https://treehacks.tzhu.dev"

    /// Voice server URL - use ngrok tunnel for Vision Pro access
    /// Run: ngrok http 8787
    /// Then paste the https URL here (e.g., "https://abc123.ngrok-free.app")
    static let voiceServerURL = " https://vacciniaceous-solar-artie.ngrok-free.dev"
}
