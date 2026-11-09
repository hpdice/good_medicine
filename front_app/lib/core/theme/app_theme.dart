import 'package:flutter/material.dart';

/// 간격 토큰 — 화면 곳곳의 매직넘버(SizedBox 4/8/12/16/24/32) 대체용.
abstract final class Gap {
  static const xs = SizedBox(height: 4, width: 4);
  static const sm = SizedBox(height: 8, width: 8);
  static const md = SizedBox(height: 12, width: 12);
  static const lg = SizedBox(height: 16, width: 16);
  static const xl = SizedBox(height: 24, width: 24);
  static const xxl = SizedBox(height: 32, width: 32);

  static const v4 = SizedBox(height: 4);
  static const v8 = SizedBox(height: 8);
  static const v12 = SizedBox(height: 12);
  static const v16 = SizedBox(height: 16);
  static const v24 = SizedBox(height: 24);
  static const v32 = SizedBox(height: 32);
}

const kScreenPadding = EdgeInsets.all(18);
const kRadius = 18.0;
const kFieldRadius = 14.0;

class AppTheme {
  AppTheme._();

  // 브랜드 — 선명한 에메랄드-틸(신뢰감 + 생기).
  static const _brand = Color(0xFF0EA47A);
  static const _brandDark = Color(0xFF34D399);

  static ThemeData get light => _build(Brightness.light);
  static ThemeData get dark => _build(Brightness.dark);

  static ThemeData _build(Brightness b) {
    final isDark = b == Brightness.dark;
    final scheme = ColorScheme.fromSeed(
      seedColor: isDark ? _brandDark : _brand,
      brightness: b,
    ).copyWith(
      primary: isDark ? _brandDark : _brand,
      surface: isDark ? const Color(0xFF17191C) : Colors.white,
    );

    final bg = isDark ? const Color(0xFF0F1113) : const Color(0xFFF4F6F8);
    final border = isDark ? const Color(0xFF2A2E33) : const Color(0xFFECEEF1);
    final fieldFill = isDark ? const Color(0xFF1E2126) : const Color(0xFFEFF1F4);
    final shadow = isDark ? Colors.black : const Color(0xFF0B1F3A);

    final base = ThemeData(colorScheme: scheme, useMaterial3: true);
    final tt = base.textTheme;

    return base.copyWith(
      scaffoldBackgroundColor: bg,
      splashFactory: InkSparkle.splashFactory,
      textTheme: tt
          .apply(bodyColor: scheme.onSurface, displayColor: scheme.onSurface)
          .copyWith(
            headlineSmall: tt.headlineSmall?.copyWith(
                fontWeight: FontWeight.w800, letterSpacing: -0.5),
            titleLarge: tt.titleLarge
                ?.copyWith(fontWeight: FontWeight.w800, letterSpacing: -0.3),
            titleMedium: tt.titleMedium?.copyWith(fontWeight: FontWeight.w700),
            titleSmall: tt.titleSmall?.copyWith(fontWeight: FontWeight.w700),
          ),
      appBarTheme: AppBarTheme(
        backgroundColor: bg,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          fontSize: 22,
          fontWeight: FontWeight.w800,
          letterSpacing: -0.4,
          color: scheme.onSurface,
        ),
      ),
      cardTheme: CardThemeData(
        elevation: isDark ? 0 : 8,
        shadowColor: shadow.withValues(alpha: isDark ? 0 : 0.06),
        color: scheme.surface,
        surfaceTintColor: Colors.transparent,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(kRadius),
          side: isDark ? BorderSide(color: border) : BorderSide.none,
        ),
      ),
      dividerTheme: DividerThemeData(color: border, space: 1, thickness: 1),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: fieldFill,
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 18),
        hintStyle: TextStyle(color: scheme.onSurfaceVariant),
        floatingLabelStyle: TextStyle(color: scheme.primary),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(kFieldRadius),
          borderSide: BorderSide.none,
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(kFieldRadius),
          borderSide: BorderSide.none,
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(kFieldRadius),
          borderSide: BorderSide(color: scheme.primary, width: 1.8),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(kFieldRadius),
          borderSide: BorderSide(color: scheme.error, width: 1.2),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size.fromHeight(54),
          elevation: 0,
          textStyle: const TextStyle(
              fontSize: 15.5, fontWeight: FontWeight.w800, letterSpacing: -0.2),
          shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(kFieldRadius)),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size.fromHeight(50),
          foregroundColor: scheme.onSurface,
          textStyle:
              const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700),
          side: BorderSide(color: isDark ? border : const Color(0xFFDDE1E6)),
          shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(kFieldRadius)),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: scheme.primary,
          textStyle: const TextStyle(fontWeight: FontWeight.w700),
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        height: 68,
        backgroundColor: scheme.surface,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        indicatorColor: scheme.primary.withValues(alpha: isDark ? 0.22 : 0.14),
        iconTheme: WidgetStateProperty.resolveWith((s) => IconThemeData(
            color: s.contains(WidgetState.selected)
                ? scheme.primary
                : scheme.onSurfaceVariant)),
        labelTextStyle: WidgetStateProperty.resolveWith((s) => TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: s.contains(WidgetState.selected)
                  ? scheme.primary
                  : scheme.onSurfaceVariant,
            )),
      ),
      chipTheme: base.chipTheme.copyWith(
        side: BorderSide(color: border),
        backgroundColor: scheme.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: scheme.surface,
        showDragHandle: true,
        clipBehavior: Clip.antiAlias,
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
        ),
      ),
    );
  }
}

/// 위험도 등급별 표시 스타일 — home_screen·ocr_result_screen이 하드코딩하던 색/라벨/아이콘을 한곳에.
/// `unjudged`는 등급이 아니라 "확인하지 못함" — 성분 정보가 없어 규칙을 적용하지 못한 약을 "안전"과 구분한다.
enum RiskTone { critical, caution, safe, unjudged }

class RiskStyle {
  final Color color;
  final Color container;
  final Color onContainer;
  final IconData icon;
  final String label;

  const RiskStyle._(
      this.color, this.container, this.onContainer, this.icon, this.label);

  static RiskStyle of(RiskTone tone, Brightness b) {
    final dark = b == Brightness.dark;
    switch (tone) {
      case RiskTone.critical:
        return RiskStyle._(
          const Color(0xFFE23D3D),
          dark ? const Color(0xFF3A1E1E) : const Color(0xFFFDEBEB),
          const Color(0xFFC42F2F),
          Icons.warning_amber_rounded,
          '병용금기',
        );
      case RiskTone.caution:
        return RiskStyle._(
          const Color(0xFFE58A00),
          dark ? const Color(0xFF362A16) : const Color(0xFFFFF3E0),
          const Color(0xFFB56C00),
          Icons.info_outline_rounded,
          '효능군 중복',
        );
      case RiskTone.safe:
        return RiskStyle._(
          const Color(0xFF12B886),
          dark ? const Color(0xFF163329) : const Color(0xFFE7F8F1),
          const Color(0xFF0B8A66),
          Icons.check_circle_outline_rounded,
          '안전',
        );
      case RiskTone.unjudged:
        return RiskStyle._(
          const Color(0xFF6B7684),
          dark ? const Color(0xFF2A2F36) : const Color(0xFFEEF1F4),
          const Color(0xFF4B5563),
          Icons.help_outline_rounded,
          '판정 불가',
        );
    }
  }

  static RiskTone? toneFromLevel(String level) => switch (level) {
        'critical' => RiskTone.critical,
        'caution' => RiskTone.caution,
        'safe' => RiskTone.safe,
        _ => null,
      };
}

/// 부드러운 그림자 카드 — Card 위젯 없이 커스텀 컨테이너에 쓰는 공통 데코.
BoxDecoration softCard(BuildContext context) {
  final scheme = Theme.of(context).colorScheme;
  final isDark = Theme.of(context).brightness == Brightness.dark;
  return BoxDecoration(
    color: scheme.surface,
    borderRadius: BorderRadius.circular(kRadius),
    border: isDark ? Border.all(color: Theme.of(context).dividerColor) : null,
    boxShadow: isDark
        ? null
        : const [
            BoxShadow(
              color: Color(0x0F0B1F3A),
              blurRadius: 18,
              offset: Offset(0, 8),
            ),
          ],
  );
}
