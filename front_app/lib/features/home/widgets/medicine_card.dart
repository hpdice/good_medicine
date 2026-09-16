import 'package:flutter/material.dart';
import '../../../core/models/medicine_box_models.dart';
import '../../../core/theme/app_theme.dart';
import '../home_provider.dart';

/// 복약함 카드 — 약 이름/효능, 위험도 점, 알림·삭제 버튼, 펼치면 효능 상세.
class MedicineCard extends StatelessWidget {
  final MedicineBoxEntry entry;
  final DrugRisk risk;
  final bool isExpanded;
  final VoidCallback onToggle;
  final VoidCallback onDelete;
  final VoidCallback onEditReminder;

  const MedicineCard({
    super.key,
    required this.entry,
    required this.risk,
    required this.isExpanded,
    required this.onToggle,
    required this.onDelete,
    required this.onEditReminder,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final drug = entry.drug;
    return Card(
      child: InkWell(
        onTap: onToggle,
        borderRadius: BorderRadius.circular(kRadius),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 12, 6, 12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              RiskDot(risk: risk),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(drug.displayName,
                          style: const TextStyle(
                              fontWeight: FontWeight.w700, fontSize: 15)),
                      if (drug.className != null) ...[
                        const SizedBox(height: 2),
                        Text(drug.className!,
                            style: TextStyle(
                                fontSize: 12,
                                color: scheme.onSurfaceVariant)),
                      ],
                      if (drug.efcyQesitm != null && !isExpanded) ...[
                        const SizedBox(height: 3),
                        Text(drug.efcyQesitm!,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                                fontSize: 12,
                                color: scheme.onSurfaceVariant)),
                      ],
                    ]),
              ),
              if (drug.etcOtcName != null)
                Container(
                  margin: const EdgeInsets.only(right: 2),
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: scheme.surfaceContainerHighest,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(drug.etcOtcName!,
                      style: TextStyle(
                          fontSize: 11, color: scheme.onSurfaceVariant)),
                ),
              IconButton(
                icon: Icon(
                  entry.reminderEnabled
                      ? Icons.alarm_on_rounded
                      : Icons.alarm_add_outlined,
                  size: 20,
                  color: entry.reminderEnabled
                      ? scheme.primary
                      : scheme.onSurfaceVariant,
                ),
                tooltip: '복약 알림 설정',
                onPressed: onEditReminder,
              ),
              IconButton(
                icon: Icon(Icons.delete_outline_rounded,
                    size: 20, color: scheme.onSurfaceVariant),
                onPressed: onDelete,
              ),
            ]),
            AnimatedCrossFade(
              duration: const Duration(milliseconds: 180),
              crossFadeState: isExpanded
                  ? CrossFadeState.showSecond
                  : CrossFadeState.showFirst,
              firstChild: const SizedBox(width: double.infinity),
              secondChild: drug.efcyQesitm != null
                  ? Padding(
                      padding: const EdgeInsets.fromLTRB(24, 10, 8, 0),
                      child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Divider(height: 1),
                            const SizedBox(height: 8),
                            Text(drug.efcyQesitm!,
                                style: TextStyle(
                                    fontSize: 12.5,
                                    height: 1.45,
                                    color: scheme.onSurfaceVariant)),
                          ]))
                  : const SizedBox(width: double.infinity),
            ),
          ]),
        ),
      ),
    );
  }
}

class RiskDot extends StatelessWidget {
  final DrugRisk risk;
  const RiskDot({super.key, required this.risk});

  @override
  Widget build(BuildContext context) {
    final b = Theme.of(context).brightness;
    final (RiskStyle? style) = switch (risk) {
      DrugRisk.contraindicated => RiskStyle.of(RiskTone.critical, b),
      DrugRisk.caution => RiskStyle.of(RiskTone.caution, b),
      DrugRisk.safe => RiskStyle.of(RiskTone.safe, b),
      DrugRisk.none => null,
    };
    if (style == null) {
      return const SizedBox(width: 22, height: 22);
    }
    return Container(
      width: 22,
      height: 22,
      decoration: BoxDecoration(color: style.container, shape: BoxShape.circle),
      child: Icon(style.icon, size: 14, color: style.color),
    );
  }
}
