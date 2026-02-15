//
//  HandTrackingManager.swift
//  treehacks26
//

import ARKit
import SwiftUI

@Observable
@MainActor
final class HandTrackingManager {
    private var arSession = ARKitSession()
    private var handTracking = HandTrackingProvider()

    private(set) var isTracking = false
    private(set) var lastGestureTime: Date?
    private(set) var gestureDetected = false

    /// Minimum seconds between gesture triggers (debounce)
    private let gestureCooldown: TimeInterval = 2.0

    /// Endpoint to call when open palm is detected
    var onOpenPalmDetected: (() async -> Void)?

    func startTracking() async {
        guard HandTrackingProvider.isSupported else {
            print("[HandTracking] Hand tracking not supported on this device")
            return
        }

        do {
            try await arSession.run([handTracking])
            isTracking = true
            print("[HandTracking] Started hand tracking")

            await processHandUpdates()
        } catch {
            print("[HandTracking] Failed to start: \(error)")
        }
    }

    func stopTracking() {
        arSession.stop()
        isTracking = false
        print("[HandTracking] Stopped hand tracking")
    }

    private func processHandUpdates() async {
        for await update in handTracking.anchorUpdates {
            guard update.event == .updated else { continue }

            let anchor = update.anchor
            guard anchor.isTracked else { continue }

            // Check for open palm gesture
            if isOpenPalm(anchor: anchor) {
                await handleOpenPalmDetected()
            }
        }
    }

    private func isOpenPalm(anchor: HandAnchor) -> Bool {
        let skeleton = anchor.handSkeleton
        guard let skeleton = skeleton else { return false }

        // Check if all fingers are extended
        let fingersExtended = [
            isFingerExtended(skeleton: skeleton, finger: .index),
            isFingerExtended(skeleton: skeleton, finger: .middle),
            isFingerExtended(skeleton: skeleton, finger: .ring),
            isFingerExtended(skeleton: skeleton, finger: .little),
            isThumbExtended(skeleton: skeleton)
        ]

        // All 5 fingers must be extended for open palm
        return fingersExtended.allSatisfy { $0 }
    }

    private enum Finger {
        case index, middle, ring, little
    }

    private func isFingerExtended(skeleton: HandSkeleton, finger: Finger) -> Bool {
        let (knuckle, intermediate, tip): (HandSkeleton.JointName, HandSkeleton.JointName, HandSkeleton.JointName)

        switch finger {
        case .index:
            knuckle = .indexFingerKnuckle
            intermediate = .indexFingerIntermediateBase
            tip = .indexFingerTip
        case .middle:
            knuckle = .middleFingerKnuckle
            intermediate = .middleFingerIntermediateBase
            tip = .middleFingerTip
        case .ring:
            knuckle = .ringFingerKnuckle
            intermediate = .ringFingerIntermediateBase
            tip = .ringFingerTip
        case .little:
            knuckle = .littleFingerKnuckle
            intermediate = .littleFingerIntermediateBase
            tip = .littleFingerTip
        }

        guard let knuckleJoint = skeleton.joint(knuckle),
              let intermediateJoint = skeleton.joint(intermediate),
              let tipJoint = skeleton.joint(tip) else {
            return false
        }

        // Get positions
        let knucklePos = knuckleJoint.anchorFromJointTransform.columns.3
        let intermediatePos = intermediateJoint.anchorFromJointTransform.columns.3
        let tipPos = tipJoint.anchorFromJointTransform.columns.3

        // Calculate vectors
        let vec1 = SIMD3<Float>(intermediatePos.x - knucklePos.x,
                                 intermediatePos.y - knucklePos.y,
                                 intermediatePos.z - knucklePos.z)
        let vec2 = SIMD3<Float>(tipPos.x - intermediatePos.x,
                                 tipPos.y - intermediatePos.y,
                                 tipPos.z - intermediatePos.z)

        // Calculate angle between segments
        let dot = simd_dot(simd_normalize(vec1), simd_normalize(vec2))

        // If dot product is close to 1, finger is straight (extended)
        // Threshold of 0.7 allows for some natural bend
        return dot > 0.7
    }

    private func isThumbExtended(skeleton: HandSkeleton) -> Bool {
        guard let knuckleJoint = skeleton.joint(.thumbKnuckle),
              let tipJoint = skeleton.joint(.thumbTip),
              let wristJoint = skeleton.joint(.wrist) else {
            return false
        }

        // For thumb, check if tip is far enough from wrist
        let tipPos = tipJoint.anchorFromJointTransform.columns.3
        let wristPos = wristJoint.anchorFromJointTransform.columns.3
        let knucklePos = knuckleJoint.anchorFromJointTransform.columns.3

        let tipToWrist = simd_distance(
            SIMD3<Float>(tipPos.x, tipPos.y, tipPos.z),
            SIMD3<Float>(wristPos.x, wristPos.y, wristPos.z)
        )
        let knuckleToWrist = simd_distance(
            SIMD3<Float>(knucklePos.x, knucklePos.y, knucklePos.z),
            SIMD3<Float>(wristPos.x, wristPos.y, wristPos.z)
        )

        // Thumb is extended if tip is significantly farther from wrist than knuckle
        return tipToWrist > knuckleToWrist * 1.3
    }

    private func handleOpenPalmDetected() async {
        // Debounce: check cooldown
        if let lastTime = lastGestureTime,
           Date().timeIntervalSince(lastTime) < gestureCooldown {
            return
        }

        lastGestureTime = Date()
        gestureDetected = true

        print("[HandTracking] Open palm detected!")

        // Call the endpoint
        await onOpenPalmDetected?()

        // Reset gesture flag after a short delay
        try? await Task.sleep(for: .milliseconds(500))
        gestureDetected = false
    }
}
