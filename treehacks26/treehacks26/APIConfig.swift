//
//  APIConfig.swift
//  treehacks26
//

import Foundation

/// Base URL for the FastAPI backend. Demo and voice (gesture-to-sound) both use this URL.
enum APIConfig {
    /// Use "http://localhost:8000" for local dev, or "https://treehacks.tzhu.dev" for Cloudflare tunnel.
    static let baseURL = "https://treehacks.tzhu.dev"

    /// WebSocket URL for demo color stream (derived from baseURL).
    static var wsDemoURL: URL? {
        let s = baseURL
            .replacingOccurrences(of: "https://", with: "wss://")
            .replacingOccurrences(of: "http://", with: "ws://")
        return URL(string: "\(s)/ws/demo")
    }
}
