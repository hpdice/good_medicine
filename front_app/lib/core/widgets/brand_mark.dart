import 'package:flutter/material.dart';

/// 앱 로고 마크 — 그라데이션 라운드 스퀘어 + 알약 아이콘 + "굿메디슨" 워드마크.
class BrandMark extends StatelessWidget {
  final bool showWordmark;
  final double size;

  const BrandMark({super.key, this.showWordmark = true, this.size = 64});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final icon = Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            scheme.primary,
            Color.lerp(scheme.primary, const Color(0xFF0B7DE8), 0.55)!,
          ],
        ),
        borderRadius: BorderRadius.circular(size * 0.3),
        boxShadow: [
          BoxShadow(
            color: scheme.primary.withValues(alpha: 0.35),
            blurRadius: 20,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: Icon(Icons.medication_liquid_rounded,
          color: Colors.white, size: size * 0.54),
    );

    if (!showWordmark) return icon;

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        icon,
        const SizedBox(height: 16),
        Text('굿메디슨',
            style: TextStyle(
              fontSize: 26,
              fontWeight: FontWeight.w900,
              letterSpacing: -0.8,
              color: scheme.onSurface,
            )),
        const SizedBox(height: 4),
        Text('내 약, 안전하게',
            style: TextStyle(
                fontSize: 13.5,
                fontWeight: FontWeight.w500,
                color: scheme.onSurfaceVariant)),
      ],
    );
  }
}
