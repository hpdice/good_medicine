import 'package:flutter/material.dart';

/// 위험도 등급 배지(예: "병용금기"/"주의"). Flutter 내장 `Badge` 위젯과 이름이
/// 겹쳐서 `AppBadge`로 부른다. `FindingCard`·`SingleDrugRiskCard`가 공유한다.
class AppBadge extends StatelessWidget {
  final String text;
  final Color color;
  const AppBadge({super.key, required this.text, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(text,
          style: const TextStyle(
              color: Colors.white, fontSize: 11.5, fontWeight: FontWeight.w700)),
    );
  }
}
