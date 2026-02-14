//
//  ContentView.swift
//  treehacks26
//
//  Created by Rachel Zhang on 2026-02-14.
//

import SwiftUI
import RealityKit

struct ContentView: View {
    @Environment(AppModel.self) private var appModel

    var body: some View {
        VStack(spacing: 20) {
            ToggleImmersiveSpaceButton()
            Button("Build an AI agent") { appModel.addAgent() }
                .disabled(appModel.immersiveSpaceState != .open)
        }
        .padding()
    }
}

#Preview(windowStyle: .automatic) {
    ContentView()
        .environment(AppModel())
}
