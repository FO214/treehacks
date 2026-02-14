//
//  ImmersiveView.swift
//  treehacks26
//
//  Office environment (Ground = floor + Office_Props_Pack). One desk per agent; spawn more as agents are added.
//

import SwiftUI
import RealityKit
import RealityKitContent

struct ImmersiveView: View {
    @Environment(AppModel.self) var appModel
    @State private var sceneState = TycoonSceneState()

    var body: some View {
        RealityView { content in
            // 1) Office environment (Ground.usda = grid floor + Office_Props_Pack cubicles, desks, etc.)
            if let office = try? await Entity(named: "Ground", in: realityKitContentBundle) {
                content.add(office)
            }
            // 2) Dynamic desks: one per agent (starts with 1)
            let tablesContainer = Entity()
            tablesContainer.name = "Tables"
            content.add(tablesContainer)
            sceneState.tablesContainer = tablesContainer
            sceneState.allocator.gridOrigin = SIMD3<Float>(0, 0, 0)
            sceneState.allocator.tableSpacingX = 0.8
            sceneState.allocator.tableSpacingZ = 0.6
            await sceneState.ensureTables(count: appModel.agentCount, contentBundle: realityKitContentBundle)
        }
        .onChange(of: appModel.agentCount) { _, newCount in
            Task { await sceneState.ensureTables(count: newCount, contentBundle: realityKitContentBundle) }
        }
    }
}

#Preview(immersionStyle: .full) {
    ImmersiveView()
        .environment(AppModel())
}
