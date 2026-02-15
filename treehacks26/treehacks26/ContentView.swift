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

            if appModel.immersiveSpaceState == .open {
                Button {
                    appModel.repositioningMode.toggle()
                } label: {
                    Label(appModel.repositioningMode ? "Done" : "Reposition", systemImage: appModel.repositioningMode ? "checkmark.circle.fill" : "hand.draw.fill")
                }
                .buttonStyle(.borderedProminent)
                .tint(appModel.repositioningMode ? .green : .blue)
            }
        }
        .padding()
    }
}

#Preview(windowStyle: .automatic) {
    ContentView()
        .environment(AppModel())
}
