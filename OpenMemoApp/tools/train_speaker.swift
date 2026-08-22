// 说话人识别模型训练工具（Apple Create ML 原生）
//
// 用法（在 Mac 上）：
//   1. 收集每个人的语音样本（每人至少 30s，越多样本越好）：
//        speaker_samples/Ethan/*.m4a
//        speaker_samples/妈妈/*.m4a
//        speaker_samples/Vincent叔叔/*.m4a
//   2. 编译并运行：
//        swiftc -o train_speaker train_speaker.swift -framework CreateML -framework Foundation
//        ./train_speaker speaker_samples
//   3. 生成的 SpeakerModel.mlmodel 拖进 Xcode 工程（target membership 勾上）
//
// 说明：Create ML 的 MLSoundClassifier 会把每个人的声音训练成一个类别，
// App 内用 SoundAnalysis 的 SNClassifySoundRequest(mlModel:) 实时推理。
// 训练数据越多、每人声音差异越大，识别越准。

import Foundation
import CreateML

guard CommandLine.arguments.count >= 2 else {
    print("用法: train_speaker <样本目录> [输出目录]")
    exit(1)
}

let dataDir = URL(fileURLWithPath: CommandLine.arguments[1])
let outDir = CommandLine.arguments.count >= 3
    ? URL(fileURLWithPath: CommandLine.arguments[2])
    : URL(fileURLWithPath: ".")

print("📂 样本目录: \(dataDir.path)")

// 检查目录结构：每个子目录 = 一个说话人
let fm = FileManager.default
let speakerDirs = (try? fm.contentsOfDirectory(
    at: dataDir,
    includingPropertiesForKeys: nil,
    options: [.skipsHiddenFiles]
)) ?? []

var totalSamples = 0
for dir in speakerDirs where dir.hasDirectoryPath {
    let files = (try? fm.contentsOfDirectory(
        at: dir, includingPropertiesForKeys: nil
    )) ?? []
    print("   \(dir.lastPathComponent): \(files.count) 个样本")
    totalSamples += files.count
}

guard totalSamples > 0 else {
    print("❌ 没有找到任何音频样本")
    exit(1)
}

print("🎧 开始训练（共 \(totalSamples) 个样本）...")

do {
    // Create ML 声音分类器训练
    let model = try MLSoundClassifier(trainingData: .labeledDirectories(at: dataDir))
    // 训练参数：窗口 3 秒（识别时也按 3 秒窗口分类，适合句子级识别）
    let metadata = MLModelMetadata(
        author: "OpenMemo",
        shortDescription: "OpenMemo 说话人识别（Apple Create ML）",
        version: "1.0"
    )
    let outputURL = outDir.appendingPathComponent("SpeakerModel.mlmodel")
    try model.write(to: outputURL, metadata: metadata)
    print("✅ 模型已保存: \(outputURL.path)")
    print("   把 SpeakerModel.mlmodel 拖进 Xcode 工程即可启用说话人识别")
} catch {
    print("❌ 训练失败: \(error)")
    exit(1)
}
