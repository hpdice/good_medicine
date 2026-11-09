import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../../core/models/drug_models.dart';
import '../../core/models/medicine_box_models.dart' show formatCount;
import '../../core/theme/app_theme.dart';
import 'camera_provider.dart';

class OcrResultScreen extends StatefulWidget {
  const OcrResultScreen({super.key});

  @override
  State<OcrResultScreen> createState() => _OcrResultScreenState();
}

class _OcrResultScreenState extends State<OcrResultScreen> {
  @override
  Widget build(BuildContext context) {
    return Consumer<CameraProvider>(builder: (context, cam, _) {
      return Scaffold(
        appBar: AppBar(title: const Text('인식 결과')),
        bottomNavigationBar: Container(
          decoration: BoxDecoration(
            color: Theme.of(context).colorScheme.surface,
            border: Border(
                top: BorderSide(color: Theme.of(context).dividerColor)),
          ),
          child: SafeArea(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                if (cam.picked.isNotEmpty) ...[
                  FilledButton.icon(
                    onPressed: () {
                      context.go('/');
                      cam.savePicked();
                    },
                    icon: const Icon(Icons.add_rounded, size: 20),
                    label: Text('내 약에 추가 (${cam.picked.length})'),
                  ),
                  Gap.v8,
                ],
                OutlinedButton.icon(
                  onPressed: () => context.go('/search'),
                  icon: const Icon(Icons.search_rounded, size: 18),
                  label: const Text('직접 검색으로 추가'),
                ),
              ]),
            ),
          ),
        ),
        body: _buildBody(context, cam),
      );
    });
  }

  Widget _buildBody(BuildContext context, CameraProvider cam) {
    if (cam.isProcessing) {
      return const Center(child: CircularProgressIndicator());
    }
    if (cam.matchResults.isEmpty) {
      final scheme = Theme.of(context).colorScheme;
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.image_search_rounded,
                size: 48, color: scheme.onSurfaceVariant),
            Gap.v16,
            Text('약품명을 인식하지 못했습니다',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.titleMedium),
            Gap.v4,
            Text('사진 각도·조명을 바꿔 다시 찍거나\n직접 검색으로 추가해 보세요.',
                textAlign: TextAlign.center,
                style: TextStyle(color: scheme.onSurfaceVariant, height: 1.5)),
            Gap.v24,
            FilledButton.icon(
              onPressed: () => context.go('/search'),
              icon: const Icon(Icons.search_rounded, size: 20),
              label: const Text('직접 검색으로 추가'),
              style: FilledButton.styleFrom(minimumSize: const Size(200, 48)),
            ),
          ]),
        ),
      );
    }
    return ListView.separated(
      padding: kScreenPadding,
      itemCount: cam.matchResults.length,
      separatorBuilder: (_, __) => const SizedBox(height: 10),
      itemBuilder: (context, i) => _MatchResultCard(
        result: cam.matchResults[i],
        isChecked: cam.isPicked,
        onToggle: (drug) =>
            cam.togglePick(drug, dose: cam.matchResults[i].dose),
        onGoSearch: () => context.go('/search'),
      ),
    );
  }
}

class _MatchResultCard extends StatelessWidget {
  final DrugNameMatchResult result;
  final bool Function(String drugId) isChecked;
  final void Function(DrugSearchResult drug) onToggle;
  final VoidCallback onGoSearch;

  const _MatchResultCard({
    required this.result,
    required this.isChecked,
    required this.onToggle,
    required this.onGoSearch,
  });

  @override
  Widget build(BuildContext context) {
    final muted = Theme.of(context).colorScheme.onSurfaceVariant;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('인식된 텍스트  “${result.queriedName}”',
              style: TextStyle(fontSize: 12, color: muted)),
          if (_doseText(result.dose) case final dose?) ...[
            const SizedBox(height: 2),
            Text('복용 안내  $dose',
                style: TextStyle(
                    fontSize: 12,
                    color: Theme.of(context).colorScheme.primary,
                    fontWeight: FontWeight.w600)),
          ],
          Gap.v8,
          if (result.matched != null)
            _DrugRow(
              drug: result.matched!,
              isChecked: isChecked(result.matched!.id),
              onToggle: () => onToggle(result.matched!),
            )
          else ...[
            Row(children: [
              Expanded(
                  child: Text('일치하는 약품 없음',
                      style: TextStyle(color: muted))),
              OutlinedButton.icon(
                onPressed: onGoSearch,
                icon: const Icon(Icons.search_rounded, size: 16),
                label: const Text('직접 검색'),
                style: OutlinedButton.styleFrom(
                    minimumSize: Size.zero,
                    padding:
                        const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                    textStyle: const TextStyle(fontSize: 12)),
              ),
            ]),
            if (result.alternatives.isNotEmpty) ...[
              Gap.v4,
              Text('유사 약품', style: TextStyle(fontSize: 12, color: muted)),
              for (final alt in result.alternatives.take(3))
                _DrugRow(
                  drug: alt,
                  isChecked: isChecked(alt.id),
                  onToggle: () => onToggle(alt),
                ),
            ],
          ],
        ]),
      ),
    );
  }
}

/// "1회 1개 · 하루 2번 · 7일" — 읽은 항목만.
String? _doseText(OcrDose? dose) {
  if (dose == null) return null;
  final parts = [
    if (dose.unitsPerIntake != null) '1회 ${formatCount(dose.unitsPerIntake!)}개',
    if (dose.timesPerDay != null) '하루 ${dose.timesPerDay}번',
    if (dose.durationDays != null) '${dose.durationDays}일',
  ];
  return parts.isEmpty ? null : parts.join(' · ');
}

class _DrugRow extends StatelessWidget {
  final DrugSearchResult drug;
  final bool isChecked;
  final VoidCallback onToggle;

  const _DrugRow(
      {required this.drug, required this.isChecked, required this.onToggle});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: onToggle,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(children: [
          Checkbox(
            value: isChecked,
            onChanged: (_) => onToggle(),
            visualDensity: VisualDensity.compact,
            materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
          ),
          const SizedBox(width: 6),
          Expanded(
            child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(drug.displayName,
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                  if (drug.className != null)
                    Text(drug.className!,
                        style: TextStyle(
                            fontSize: 12,
                            color: Theme.of(context)
                                .colorScheme
                                .onSurfaceVariant)),
                ]),
          ),
        ]),
      ),
    );
  }
}
