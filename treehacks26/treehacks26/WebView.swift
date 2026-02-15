//
//  WebView.swift
//  treehacks26
//

import SwiftUI
import WebKit

struct WebView: UIViewRepresentable {
    let url: URL?

    func makeUIView(context: Context) -> WKWebView {
        let webView = WKWebView()
        webView.scrollView.isScrollEnabled = true
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        guard let url else { return }
        // Only load when URL changes to avoid reload loops and ensure correct link loads
        if context.coordinator.lastLoadedURL != url {
            context.coordinator.lastLoadedURL = url
            webView.load(URLRequest(url: url))
        }
    }

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    class Coordinator {
        var lastLoadedURL: URL?
    }
}

/// WebView with a close button; persists until user taps close.
struct WebViewWithClose: View {
    let url: URL?
    let onClose: () -> Void

    var body: some View {
        ZStack(alignment: .topTrailing) {
            WebView(url: url)
            Button(action: onClose) {
                Image(systemName: "xmark.circle.fill")
                    .font(.system(size: 44))
                    .symbolRenderingMode(.hierarchical)
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
            .padding(16)
        }
    }
}
