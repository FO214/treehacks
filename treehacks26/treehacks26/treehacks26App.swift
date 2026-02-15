//
//  treehacks26App.swift
//  treehacks26
//
//  Created by Rachel Zhang on 2026-02-14.
//

import SwiftUI

@main
struct treehacks26App: App {
    @Environment(\.scenePhase) private var scenePhase
    @State private var appModel = AppModel()
    @State private var avPlayerViewModel = AVPlayerViewModel()

    var body: some Scene {
        WindowGroup {
            if avPlayerViewModel.isPlaying {
                AVPlayerView(viewModel: avPlayerViewModel)
            } else {
                ContentView()
                    .environment(appModel)
            }
        }
        .windowStyle(.plain)
        .windowResizability(.contentSize)
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .background {
                exit(0)
            }
        }

        WindowGroup("Vercel Preview") {
            WebView(url: URL(string: "https://treehacks-agent-repo.vercel.app"))
                .frame(minWidth: 600, minHeight: 450)
                .glassBackgroundEffect(in: .rect(cornerRadius: 16))
        }
        .windowResizability(.contentSize)
        .defaultSize(width: 600, height: 450)

        ImmersiveSpace(id: appModel.immersiveSpaceID) {
            ImmersiveView()
                .environment(appModel)
                .onAppear { appModel.immersiveSpaceState = .open }
                .onDisappear {
                    appModel.immersiveSpaceState = .closed
                    avPlayerViewModel.reset()
                }
        }
        .immersionStyle(selection: .constant(.mixed), in: .mixed)
    }
}
