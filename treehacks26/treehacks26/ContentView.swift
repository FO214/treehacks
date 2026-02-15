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
        HStack(spacing: 12) {
            Image("palo-alto")
                .resizable()
                .aspectRatio(contentMode: .fit)
                .frame(height: 84)

            VStack(spacing: 8) {
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
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .fixedSize()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.black)
        .glassBackgroundEffect(in: .rect(cornerRadius: 16), displayMode: .always)
        .ignoresSafeArea()
        .persistentSystemOverlays(.hidden)
    }
}

#Preview(windowStyle: .automatic) {
    ContentView()
        .environment(AppModel())
}
