import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../core/models/analysis_models.dart';
import '../../core/models/medicine_box_models.dart';
import 'home_provider.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _expanded = <String>{};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback(
        (_) => context.read<HomeProvider>().loadEntries());
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<HomeProvider>(builder: (context, home, _) {
      return Scaffold(
        appBar: AppBar(title: const Text('내 약 목록')),
        body: _buildBody(context, home),
      );
    });
  }

  Widget _buildBody(BuildContext context, HomeProvider home) {
    if (home.isLoading && home.entries.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    if (home.entries.isEmpty) {
      return const Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text('등록된 약이 없습니다.'),
          SizedBox(height: 8),
          Text('검색이나 카메라로 약을 추가해 보세요.',
              style: TextStyle(color: Colors.grey)),
        ]),
      );
    }

    return Stack(children: [
      ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (home.checkResult != null)
            _InteractionBanner(result: home.checkResult!),
          if (home.checkResult != null) const SizedBox(height: 8),
          ...home.entries.map((entry) {
            final risk = home.riskMap[entry.drug.id] ?? DrugRisk.none;
            return Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: _MedicineCard(
                entry: entry,
                risk: risk,
                isExpanded: _expanded.contains(entry.id),
                onToggle: () => setState(() {
                  _expanded.contains(entry.id)
                      ? _expanded.remove(entry.id)
                      : _expanded.add(entry.id);
                }),
                onDelete: () => home.deleteEntry(entry.id),
              ),
            );
          }),
        ],
      ),
      if (home.error != null)
        Positioned(
          bottom: 16,
          left: 16,
          right: 16,
          child: Material(
            elevation: 4,
            borderRadius: BorderRadius.circular(8),
            color: Theme.of(context).colorScheme.errorContainer,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              child: Row(children: [
                Expanded(
                    child: Text(home.error!,
                        style: TextStyle(
                            color: Theme.of(context)
                                .colorScheme
                                .onErrorContainer))),
                TextButton(
                    onPressed: home.clearError, child: const Text('닫기')),
              ]),
            ),
          ),
        ),
    ]);
  }
}

class _InteractionBanner extends StatelessWidget {
  final QuickCheckResponse result;
  const _InteractionBanner({required this.result});

  @override
  Widget build(BuildContext context) {
    final isCritical = result.riskLevel == 'critical';
    final bgColor =
        isCritical ? const Color(0xFFB71C1C) : const Color(0xFF4CAF50);
    final label = isCritical
        ? '병용금기 ${result.contraindicatedCount}건'
        : '안전 — 상호작용 없음';
    final icon = isCritical ? Icons.warning_amber_rounded : Icons.check_circle;

    return GestureDetector(
      onTap: isCritical ? () => _showFindings(context, result) : null,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        decoration:
            BoxDecoration(color: bgColor, borderRadius: BorderRadius.circular(12)),
        child: Row(children: [
          Icon(icon, color: Colors.white),
          const SizedBox(width: 8),
          Expanded(
              child: Text(label,
                  style: const TextStyle(
                      color: Colors.white, fontWeight: FontWeight.w600))),
          if (isCritical)
            const Icon(Icons.chevron_right, color: Colors.white),
        ]),
      ),
    );
  }

  void _showFindings(BuildContext context, QuickCheckResponse result) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(16))),
      builder: (_) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.5,
        builder: (_, ctrl) => ListView(
          controller: ctrl,
          padding: const EdgeInsets.all(16),
          children: [
            Text('병용금기 ${result.contraindicatedCount}건',
                style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 12),
            ...result.findings.map((f) => _FindingCard(finding: f)),
          ],
        ),
      ),
    );
  }
}

class _FindingCard extends StatelessWidget {
  final FindingItem finding;
  const _FindingCard({required this.finding});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Text('${finding.drug1Name} × ${finding.drug2Name}',
                  style: const TextStyle(fontWeight: FontWeight.w600)),
            ),
            Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                  color: const Color(0xFFF44336),
                  borderRadius: BorderRadius.circular(4)),
              child: const Text('병용 금기',
                  style: TextStyle(color: Colors.white, fontSize: 12)),
            ),
          ]),
          if (finding.mechanism != null) ...[
            const SizedBox(height: 6),
            Text('금기 사유:',
                style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: Theme.of(context).colorScheme.error)),
            Text(finding.mechanism!,
                style:
                    TextStyle(fontSize: 12, color: Colors.grey.shade700)),
          ],
        ]),
      ),
    );
  }
}

class _MedicineCard extends StatelessWidget {
  final MedicineBoxEntry entry;
  final DrugRisk risk;
  final bool isExpanded;
  final VoidCallback onToggle;
  final VoidCallback onDelete;

  const _MedicineCard({
    required this.entry,
    required this.risk,
    required this.isExpanded,
    required this.onToggle,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    final drug = entry.drug;
    return Card(
      child: InkWell(
        onTap: onToggle,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              _RiskIcon(risk: risk),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(drug.displayName,
                          style: const TextStyle(fontWeight: FontWeight.w500)),
                      if (drug.className != null)
                        Text(drug.className!,
                            style: TextStyle(
                                fontSize: 12, color: Colors.grey.shade600)),
                    ]),
              ),
              if (drug.etcOtcName != null)
                Chip(
                    label: Text(drug.etcOtcName!,
                        style: const TextStyle(fontSize: 11)),
                    padding: EdgeInsets.zero,
                    visualDensity: VisualDensity.compact),
              IconButton(
                icon: Icon(Icons.delete_outline,
                    color: Theme.of(context).colorScheme.error),
                onPressed: onDelete,
              ),
            ]),
            AnimatedCrossFade(
              duration: const Duration(milliseconds: 200),
              crossFadeState: isExpanded
                  ? CrossFadeState.showSecond
                  : CrossFadeState.showFirst,
              firstChild: const SizedBox.shrink(),
              secondChild: drug.efcyQesitm != null
                  ? Padding(
                      padding: const EdgeInsets.only(top: 8, left: 12),
                      child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Divider(),
                            const SizedBox(height: 4),
                            Text(drug.efcyQesitm!,
                                style: TextStyle(
                                    fontSize: 12, color: Colors.grey.shade700)),
                          ]))
                  : const SizedBox.shrink(),
            ),
          ]),
        ),
      ),
    );
  }
}

class _RiskIcon extends StatelessWidget {
  final DrugRisk risk;
  const _RiskIcon({required this.risk});

  @override
  Widget build(BuildContext context) {
    return switch (risk) {
      DrugRisk.contraindicated => const Icon(Icons.warning_amber_rounded,
          color: Color(0xFFF44336), size: 24),
      DrugRisk.safe =>
        const Icon(Icons.check_circle, color: Color(0xFF4CAF50), size: 24),
      DrugRisk.none => const SizedBox(width: 24, height: 24),
    };
  }
}
