//
//  HandTrackingManager.swift
//  treehacks26
//

import ARKit
import SwiftUI

@Observable
@MainActor
final class HandTrackingManager {
    /// Create fresh instances each time - ARKitSession cannot be restarted after stop()
    private var arSession = ARKitSession()
    private var handTracking = HandTrackingProvider()
    private var worldTracking = WorldTrackingProvider()
    private var processTask: Task<Void, Never>?

    private(set) var isTracking = false
    private(set) var lastGestureTime: Date?
    private(set) var gestureDetected = false

    /// Minimum seconds between gesture triggers (debounce)
    private let gestureCooldown: TimeInterval = 2.0

    /// Set to true to log per-finger debug info to console
    var debugEnabled = true

    /// Throttle debug logs (seconds between logs)
    private var lastDebugLogTime: Date?
    private let debugLogInterval: TimeInterval = 1.5

    /// When true, open palm triggers drag callback instead of trigger callback
    var isRepositioningMode = false

    /// Called when open palm detected (normal mode) - debounced
    var onOpenPalmDetected: (() async -> Void)?

    /// Called every frame when open palm in repositioning mode - receives HandAnchor for chirality
    var onOpenPalmForDrag: ((HandAnchor) -> Void)?

    /// Device anchor for gaze-based positioning (WorldTrackingProvider must be running).
    func queryDeviceAnchor() -> DeviceAnchor? {
        guard worldTracking.state == .running else { return nil }
        return worldTracking.queryDeviceAnchor(atTimestamp: CACurrentMediaTime())
    }

    /// True if either hand currently has an open palm (for gaze repositioning gate).
    func isPalmCurrentlyOpen() -> Bool {
        let anchors = handTracking.latestAnchors
        if let left = anchors.leftHand, isOpenPalm(anchor: left) { return true }
        if let right = anchors.rightHand, isOpenPalm(anchor: right) { return true }
        return false
    }

    func startTracking() async {
        guard HandTrackingProvider.isSupported else {
            print("[HandTracking] Hand tracking not supported on this device")
            return
        }

        do {
            try await arSession.run([handTracking, worldTracking])
            isTracking = true
            print("[HandTracking] Started hand tracking")

            processTask = Task { await processHandUpdates(handTracking) }
        } catch {
            print("[HandTracking] Failed to start: \(error)")
        }
    }

    func stopTracking() {
        processTask?.cancel()
        processTask = nil
        arSession.stop()
        isTracking = false
        // Create fresh instances for next start - ARKitSession cannot be restarted after stop()
        arSession = ARKitSession()
        handTracking = HandTrackingProvider()
        worldTracking = WorldTrackingProvider()
        print("[HandTracking] Stopped hand tracking")
    }

    private func processHandUpdates(_ provider: HandTrackingProvider) async {
        var updateCount = 0
        var notTrackedCount = 0
        var trackedCount = 0

        for await update in provider.anchorUpdates {
            guard !Task.isCancelled else { return }
            if update.event != .updated && update.event != .added { continue }
            if debugEnabled, update.event == .added, shouldLogDebug() {
                print("[HandTracking] Hand anchor added")
            }

            let anchor = update.anchor
            updateCount += 1

            if !anchor.isTracked {
                notTrackedCount += 1
                if debugEnabled, shouldLogDebug() {
                    print("[HandTracking] Hand not tracked (total: \(updateCount), tracked: \(trackedCount), notTracked: \(notTrackedCount))")
                }
                continue
            }

            trackedCount += 1
            if trackedCount == 1, debugEnabled {
                print("[HandTracking] First tracked hand received")
            }

            // Check for open palm gesture
            guard isOpenPalm(anchor: anchor) else { continue }

            if isRepositioningMode {
                onOpenPalmForDrag?(anchor)
            } else {
                await handleOpenPalmDetected()
            }
        }
    }

    private func shouldLogDebug() -> Bool {
        let now = Date()
        guard let last = lastDebugLogTime else {
            lastDebugLogTime = now
            return true
        }
        if now.timeIntervalSince(last) >= debugLogInterval {
            lastDebugLogTime = now
            return true
        }
        return false
    }

    private func isOpenPalm(anchor: HandAnchor) -> Bool {
        let skeleton = anchor.handSkeleton
        guard let skeleton = skeleton else {
            if debugEnabled, shouldLogDebug() { print("[HandTracking] No hand skeleton") }
            return false
        }

        let (indexExt, indexDot) = fingerExtendedWithDot(skeleton: skeleton, finger: .index)
        let (middleExt, middleDot) = fingerExtendedWithDot(skeleton: skeleton, finger: .middle)
        let (ringExt, ringDot) = fingerExtendedWithDot(skeleton: skeleton, finger: .ring)
        let (littleExt, littleDot) = fingerExtendedWithDot(skeleton: skeleton, finger: .little)
        let thumbExt = isThumbExtended(skeleton: skeleton)

        let fingersExtended = [indexExt, middleExt, ringExt, littleExt, thumbExt]
        let allExtended = fingersExtended.allSatisfy { $0 }

        if debugEnabled, shouldLogDebug() {
            let failed = ["index", "middle", "ring", "little", "thumb"].enumerated()
                .filter { !fingersExtended[$0.offset] }
                .map(\.element)
            print("[HandTracking] Palm: idx=\(String(format: "%.2f", indexDot)) mid=\(String(format: "%.2f", middleDot)) ring=\(String(format: "%.2f", ringDot)) little=\(String(format: "%.2f", littleDot)) thumb=\(thumbExt) → \(allExtended ? "OPEN" : "closed (\(failed))")")
        }

        return allExtended
    }

    private enum Finger {
        case index, middle, ring, little
    }

    private func isFingerExtended(skeleton: HandSkeleton, finger: Finger) -> Bool {
        let (extended, dot) = fingerExtendedWithDot(skeleton: skeleton, finger: finger)
        return extended
    }

    /// Returns (isExtended, dotProduct). Dot > 0.7 = straight finger.
    private func fingerExtendedWithDot(skeleton: HandSkeleton, finger: Finger) -> (Bool, Float) {
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

        let knuckleJoint = skeleton.joint(knuckle)
        let intermediateJoint = skeleton.joint(intermediate)
        let tipJoint = skeleton.joint(tip)

        let knucklePos = knuckleJoint.anchorFromJointTransform.columns.3
        let intermediatePos = intermediateJoint.anchorFromJointTransform.columns.3
        let tipPos = tipJoint.anchorFromJointTransform.columns.3

        let vec1 = SIMD3<Float>(intermediatePos.x - knucklePos.x,
                                 intermediatePos.y - knucklePos.y,
                                 intermediatePos.z - knucklePos.z)
        let vec2 = SIMD3<Float>(tipPos.x - intermediatePos.x,
                                 tipPos.y - intermediatePos.y,
                                 tipPos.z - intermediatePos.z)

        let dot = simd_dot(simd_normalize(vec1), simd_normalize(vec2))
        return (dot > 0.7, dot)
    }

    private func isThumbExtended(skeleton: HandSkeleton) -> Bool {
        let knuckleJoint = skeleton.joint(.thumbKnuckle)
        let tipJoint = skeleton.joint(.thumbTip)
        let wristJoint = skeleton.joint(.wrist)

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
