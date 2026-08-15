import SwiftUI

// MARK: - Color Palette
enum OMColors {
    // Backgrounds
    static let background = Color(hex: "0A0A0F")
    static let surface = Color(hex: "14141B")
    static let surfaceElevated = Color(hex: "1E1E28")
    static let glass = Color.white.opacity(0.08)
    
    // Accents
    static let primaryGradient = LinearGradient(
        colors: [Color(hex: "FF6B6B"), Color(hex: "4ECDC4")],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )
    
    static let auroraGradient = LinearGradient(
        colors: [
            Color(hex: "7C6FF0"),
            Color(hex: "6B5CE0")
        ],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )
    
    // Semantic
    static let success = Color(hex: "34D399")
    static let warning = Color(hex: "FBBF24")
    static let error = Color(hex: "F87171")
    static let info = Color(hex: "60A5FA")
    
    // Priority
    static func priority(_ level: String?) -> Color {
        switch level?.lowercased() {
        case "high": return Color(hex: "EF4444")
        case "medium": return Color(hex: "F59E0B")
        case "low": return Color(hex: "10B981")
        default: return Color(hex: "6B7280")
        }
    }
}

// MARK: - Typography
enum OMFonts {
    static let largeTitle = Font.system(.largeTitle, design: .rounded).weight(.bold)
    static let title = Font.system(.title, design: .rounded).weight(.semibold)
    static let title2 = Font.system(.title2, design: .rounded).weight(.semibold)
    static let title3 = Font.system(.title3, design: .rounded).weight(.medium)
    static let body = Font.system(.body, design: .rounded)
    static let callout = Font.system(.callout, design: .rounded)
    static let subheadline = Font.system(.subheadline, design: .rounded)
    static let caption = Font.system(.caption, design: .rounded)
    static let caption2 = Font.system(.caption2, design: .rounded)
}

// MARK: - Shadows & Effects
enum OMEffects {
    static let softShadow = ShadowStyle(
        color: .black.opacity(0.2),
        radius: 20,
        x: 0,
        y: 10
    )
    
    static let glow = ShadowStyle(
        color: OMColors.success.opacity(0.5),
        radius: 20,
        x: 0,
        y: 0
    )
    
    static let cardShadow = ShadowStyle(
        color: .black.opacity(0.15),
        radius: 16,
        x: 0,
        y: 8
    )
}

struct ShadowStyle {
    let color: Color
    let radius: CGFloat
    let x: CGFloat
    let y: CGFloat
}

// MARK: - View Modifiers
struct GlassCard: ViewModifier {
    let cornerRadius: CGFloat
    
    func body(content: Content) -> some View {
        content
            .background(.ultraThinMaterial)
            .background(OMColors.glass)
            .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .stroke(Color.white.opacity(0.1), lineWidth: 1)
            )
            .shadow(color: .black.opacity(0.2), radius: 16, x: 0, y: 8)
    }
}

struct GlowEffect: ViewModifier {
    let color: Color
    let isActive: Bool
    
    func body(content: Content) -> some View {
        content
            .shadow(color: isActive ? color.opacity(0.6) : .clear, radius: isActive ? 20 : 0)
            .animation(.easeInOut(duration: 0.3), value: isActive)
    }
}

struct Shimmer: ViewModifier {
    @State private var isAnimating = false
    
    func body(content: Content) -> some View {
        content
            .overlay(
                GeometryReader { geo in
                    LinearGradient(
                        colors: [
                            .clear,
                            .white.opacity(0.15),
                            .clear
                        ],
                        startPoint: .leading,
                        endPoint: .trailing
                    )
                    .frame(width: geo.size.width * 2)
                    .offset(x: isAnimating ? geo.size.width : -geo.size.width)
                }
                .mask(content)
            )
            .onAppear {
                withAnimation(.linear(duration: 2).repeatForever(autoreverses: false)) {
                    isAnimating = true
                }
            }
        }
}

// MARK: - Shared Background component (each panel picks its own variant → distinct wallpapers)
struct OMBackground: View {
    enum Variant {
        case chat      // purple/pink aurora, top-left
        case tasks     // indigo/blue aurora, top-right
        case settings  // teal/cyan aurora, bottom-left
        
        var colors: [Color] {
            switch self {
            case .chat:    return [Color(hex: "7C6FF0"), Color(hex: "C46BF0")]
            case .tasks:   return [Color(hex: "5B8DEF"), Color(hex: "4C6FE0")]
            case .settings: return [Color(hex: "3EC6C0"), Color(hex: "2E9EC0")]
            }
        }
        
        var offset: (x: CGFloat, y: CGFloat) {
            switch self {
            case .chat:    return (x: -0.20, y: -0.15)   // top-left, fully visible
            case .tasks:   return (x: 0.35, y: -0.05)    // top-right, fully visible
            case .settings: return (x: 0.10, y: 0.35)    // bottom
            }
        }
    }
    
    let variant: Variant
    
    init(_ variant: Variant = .chat) {
        self.variant = variant
    }
    
    var body: some View {
        ZStack {
            OMColors.background
            
            GeometryReader { geo in
                // Primary aurora
                Circle()
                    .fill(LinearGradient(colors: variant.colors, startPoint: .topLeading, endPoint: .bottomTrailing))
                    .frame(width: geo.size.width * 1.3, height: geo.size.width * 1.3)
                    .blur(radius: 110)
                    .offset(x: geo.size.width * variant.offset.x, y: geo.size.height * variant.offset.y)
                    .opacity(variant == .chat ? 0.30 : 0.5)
                
                // Secondary soft glow (only on tasks/settings — chat stays clean)
                if variant != .chat {
                    Circle()
                        .fill(variant.colors[1].opacity(0.2))
                        .frame(width: geo.size.width * 0.8, height: geo.size.width * 0.8)
                        .blur(radius: 110)
                        .offset(x: geo.size.width * -variant.offset.x * 0.8, y: geo.size.height * -variant.offset.y * 0.8)
                }
            }
        }
        .ignoresSafeArea()
    }
}

// MARK: - Hover Glow (elements glow softly when the mouse is over them)
struct HoverGlow: ViewModifier {
    @State private var isHovered = false
    var cornerRadius: CGFloat = 14
    var glowColor: Color = .white
    
    func body(content: Content) -> some View {
        content
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .stroke(isHovered ? glowColor.opacity(0.5) : Color.clear, lineWidth: 1.2)
            )
            .shadow(color: isHovered ? glowColor.opacity(0.5) : .clear, radius: isHovered ? 12 : 0)
            .brightness(isHovered ? 0.08 : 0)
            .scaleEffect(isHovered ? 1.06 : 1)
            .animation(.easeInOut(duration: 0.15), value: isHovered)
            .onHover { hovering in
                isHovered = hovering
            }
    }
}

extension View {
    /// Soft glow while the mouse hovers over this element
    func hoverGlow(cornerRadius: CGFloat = 14, glowColor: Color = .white) -> some View {
        modifier(HoverGlow(cornerRadius: cornerRadius, glowColor: glowColor))
    }
}

// MARK: - View Extensions
struct OMBackgroundModifier: ViewModifier {
    func body(content: Content) -> some View {
        content.background(OMBackground())
    }
}

extension View {
    /// Apply the shared OpenMemo background (same on every panel)
    func omBackground() -> some View {
        modifier(OMBackgroundModifier())
    }
}

// MARK: - View Extensions
extension View {
    func glass(cornerRadius: CGFloat = 20) -> some View {
        modifier(GlassCard(cornerRadius: cornerRadius))
    }
    
    func glow(color: Color, isActive: Bool) -> some View {
        modifier(GlowEffect(color: color, isActive: isActive))
    }
    
    func shimmer() -> some View {
        modifier(Shimmer())
    }
}

// MARK: - Animations
enum OMAnimations {
    static let spring = Animation.spring(response: 0.4, dampingFraction: 0.8)
    static let smooth = Animation.easeInOut(duration: 0.3)
    static let bounce = Animation.spring(response: 0.5, dampingFraction: 0.6)
}

// MARK: - Color Hex Helper
extension Color {
    init(hex: String) {
        let hex = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var int: UInt64 = 0
        Scanner(string: hex).scanHexInt64(&int)
        let a, r, g, b: UInt64
        switch hex.count {
        case 3: // RGB (12-bit)
            (a, r, g, b) = (255, (int >> 8) * 17, (int >> 4 & 0xF) * 17, (int & 0xF) * 17)
        case 6: // RGB (24-bit)
            (a, r, g, b) = (255, int >> 16, int >> 8 & 0xFF, int & 0xFF)
        case 8: // ARGB (32-bit)
            (a, r, g, b) = (int >> 24, int >> 16 & 0xFF, int >> 8 & 0xFF, int & 0xFF)
        default:
            (a, r, g, b) = (1, 1, 1, 0)
        }
        self.init(
            .sRGB,
            red: Double(r) / 255,
            green: Double(g) / 255,
            blue: Double(b) / 255,
            opacity: Double(a) / 255
        )
    }
}

// MARK: - Button Styles
struct OMProminentButton: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(OMFonts.callout.weight(.semibold))
            .foregroundStyle(.white)
            .padding(.horizontal, 20)
            .padding(.vertical, 12)
            .background(
                OMColors.primaryGradient
                    .opacity(configuration.isPressed ? 0.8 : 1)
            )
            .clipShape(Capsule())
            .scaleEffect(configuration.isPressed ? 0.96 : 1)
            .animation(.easeInOut(duration: 0.15), value: configuration.isPressed)
    }
}

struct OMGhostButton: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(OMFonts.callout.weight(.medium))
            .foregroundStyle(.primary)
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(Color.white.opacity(configuration.isPressed ? 0.15 : 0.08))
            .clipShape(Capsule())
    }
}

// MARK: - Previews
#Preview {
    ZStack {
        OMColors.background.ignoresSafeArea()
        
        VStack(spacing: 20) {
            Text("Design System")
                .font(OMFonts.largeTitle)
                .foregroundStyle(.white)
            
            HStack(spacing: 12) {
                Circle()
                    .fill(OMColors.priority("high"))
                    .frame(width: 40, height: 40)
                    .glow(color: OMColors.priority("high"), isActive: true)
                
                Circle()
                    .fill(OMColors.priority("medium"))
                    .frame(width: 40, height: 40)
                
                Circle()
                    .fill(OMColors.priority("low"))
                    .frame(width: 40, height: 40)
            }
            
            Text("Glass Card")
                .font(OMFonts.body)
                .foregroundStyle(.white)
                .padding(30)
                .glass()
            
            Button("Prominent") {}
                .buttonStyle(OMProminentButton())
            
            Button("Ghost") {}
                .buttonStyle(OMGhostButton())
        }
    }
}
