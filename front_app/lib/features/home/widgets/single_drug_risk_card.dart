import 'package:flutter/material.dart';
import '../../../core/theme/app_theme.dart';
import 'risk_badge.dart';

/// 약품 1개 단위 위험(알레르기 충돌·특정연령대금기·노인주의) 카드 — 사용자
/// 프로필 대 약품 대조라 `FindingCard`(약품 쌍)와 달리 상대 약이 없다.
class SingleDrugRiskCard extends StatelessWidget {
  final String drugName;
  final RiskTone tone;
  final String reasonLabel;
  final String reasonText;
  const SingleDrugRiskCard({
    super.key,
    required this.drugName,
    required this.tone,
    required this.reasonLabel,
    required this.reasonText,
  });

  @override
  Widget build(BuildContext context) {
    final style = RiskStyle.of(tone, Theme.of(context).brightness);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Text(drugName,
                  style: const TextStyle(
                      fontWeight: FontWeight.w700, fontSize: 14.5)),
            ),
            const SizedBox(width: 8),
            AppBadge(text: style.label, color: style.color),
          ]),
          Gap.v8,
          Text(reasonLabel,
              style: TextStyle(
                  fontSize: 12, fontWeight: FontWeight.w700, color: style.color)),
          const SizedBox(height: 2),
          Text(reasonText,
              style: TextStyle(
                  fontSize: 12.5,
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                  height: 1.4)),
        ]),
      ),
    );
  }
}
