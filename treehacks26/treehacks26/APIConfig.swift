//
//  APIConfig.swift
//  treehacks26
//

import Foundation

/// Base URL for the FastAPI backend.
enum APIConfig {
    /// Use "http://localhost:8000" for local dev, ngrok URL, or "https://treehacks.tzhu.dev" for Cloudflare.
    /// For ngrok: run `ngrok http 8000` and paste the https URL here.
    static let baseURL = "https://treehacks.tzhu.dev"

    /// Voice server URL - ngrok tunnel for Vision Pro access.
    /// Run: ngrok http 8787
    static let voiceServerURL = "https://vacciniaceous-solar-artie.ngrok-free.dev"
}
