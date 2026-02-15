//
//  ImmersiveView.swift
//  treehacks26
//

import SwiftUI
import RealityKit

/// Holds the demo block entity so we can update its material when value changes.
@Observable
final class DemoBlockState {
    var entity: ModelEntity?
}

struct ImmersiveView: View {
    @Environment(AppModel.self) private var appModel
    @State private var demoValue: Int = 0
    @State private var blockState = DemoBlockState()

    var body: some View {
        RealityView { content in
            // Create a box 1m in front of the user, ~eye level
            let box = MeshResource.generateBox(size: [0.3, 0.3, 0.3])
            let material = SimpleMaterial(color: colorForValue(demoValue), isMetallic: false)
            let entity = ModelEntity(mesh: box, materials: [material])
            entity.name = "demoBlock"

            let anchor = AnchorEntity(world: SIMD3<Float>(0, 0, -1.2))
            anchor.addChild(entity)
            content.add(anchor)

            blockState.entity = entity
        } update: { _ in
            guard let entity = blockState.entity else { return }
            guard var modelComponent = entity.components[ModelComponent.self] else { return }
            let newMaterial = SimpleMaterial(color: colorForValue(demoValue), isMetallic: false)
            modelComponent.materials = [newMaterial]
            entity.components[ModelComponent.self] = modelComponent
        }
        .onAppear {
            startPolling()
        }
    }

    private func colorForValue(_ value: Int) -> UIColor {
        value == 1 ? .systemGreen : .systemRed
    }

    private func startPolling() {
        Task {
            while true {
                await fetchDemoValue()
                try? await Task.sleep(for: .seconds(2))
            }
        }
    }

    private func fetchDemoValue() async {
        guard let url = URL(string: "\(APIConfig.baseURL)/demo/value") else { return }
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            if let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
               let value = json["value"] as? Int {
                await MainActor.run {
                    demoValue = value
                }
            }
        } catch {
            // Silently ignore network errors (e.g. backend not running)
        }
    }
}

#Preview(immersionStyle: .mixed) {
    ImmersiveView()
        .environment(AppModel())
}
