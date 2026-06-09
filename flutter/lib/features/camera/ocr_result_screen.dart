import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../../core/models/drug_models.dart';
import 'camera_provider.dart';

class OcrResultScreen extends StatefulWidget {
  const OcrResultScreen({super.key});

  @override
  State<OcrResultScreen> createState() => _OcrResultScreenState();
}

class _OcrResultScreenState extends State<OcrResultScreen> {
  final _checked = <String>{};

  @override
  Widget build(BuildContext context) {
    return Consumer<CameraProvider>(builder: (context, cam, _) {
      if (cam.addDoneCount > 0) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          cam.resetAddDone();
          context.go('/');
        });
      }
      return Scaffold(
        appBar: AppBar(
          title: const Text('OCR 결과'),
          leading: IconButton(
            icon: const Icon(Icons.arrow_back),
            onPressed: () => context.pop(),
          ),
        ),
        bottomNavigationBar: _checked.isNotEmpty
            ? SafeArea(
                child: Padding(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  child: FilledButton(
                    onPressed: cam.isAddingToBox
                        ? null
                        : () => cam.addDrugsToBox(_checked.toList()),
                    child: cam.isAddingToBox
                        ? const SizedBox(
                            height: 20,
                            width: 20,
                            child: CircularProgressIndicator(strokeWidth: 2))
                        : Text('내 약에 추가 (${_checked.length}개)'),
                  ),
                ),
              )
            : null,
        body: _buildBody(context, cam),
      );
    });
  }

  Widget _buildBody(BuildContext context, CameraProvider cam) {
    if (cam.isProcessing) {
      return const Center(child: CircularProgressIndicator());
    }
    if (cam.error != null && cam.matchResults.isEmpty) {
      return Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(cam.error!),
          const SizedBox(height: 16),
          FilledButton(
            onPressed: () => context.go('/'),
            child: const Text('검색으로 이동'),
          ),
        ]),
      );
    }
    if (cam.matchResults.isEmpty) {
      return const Center(child: Text('추출된 약품명이 없습니다.'));
    }
    return ListView.separated(
      padding: const EdgeInsets.all(16),
      itemCount: cam.matchResults.length,
      separatorBuilder: (_, __) => const SizedBox(height: 8),
      itemBuilder: (context, i) => _MatchResultCard(
        result: cam.matchResults[i],
        checked: _checked,
        onToggle: (id) => setState(() {
          _checked.contains(id) ? _checked.remove(id) : _checked.add(id);
        }),
        onGoSearch: () => context.go('/search'),
      ),
    );
  }
}

class _MatchResultCard extends StatelessWidget {
  final DrugNameMatchResult result;
  final Set<String> checked;
  final void Function(String) onToggle;
  final VoidCallback onGoSearch;

  const _MatchResultCard({
    required this.result,
    required this.checked,
    required this.onToggle,
    required this.onGoSearch,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('검색어: "${result.queriedName}"',
              style: TextStyle(fontSize: 12, color: Colors.grey.shade600)),
          const SizedBox(height: 8),
          if (result.matched != null) ...[
            _DrugRow(
              drug: result.matched!,
              isChecked: checked.contains(result.matched!.id),
              onToggle: () => onToggle(result.matched!.id),
            ),
          ] else ...[
            Row(children: [
              Expanded(
                  child: Text('매칭 결과 없음',
                      style: TextStyle(color: Colors.grey.shade500))),
              OutlinedButton.icon(
                onPressed: onGoSearch,
                icon: const Icon(Icons.search, size: 16),
                label: const Text('직접 검색'),
                style: OutlinedButton.styleFrom(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    textStyle: const TextStyle(fontSize: 12)),
              ),
            ]),
            if (result.alternatives.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text('유사 약품:',
                  style:
                      TextStyle(fontSize: 12, color: Colors.grey.shade600)),
              ...result.alternatives.take(3).map((alt) => _DrugRow(
                    drug: alt,
                    isChecked: checked.contains(alt.id),
                    onToggle: () => onToggle(alt.id),
                  )),
            ],
          ],
        ]),
      ),
    );
  }
}

class _DrugRow extends StatelessWidget {
  final DrugSearchResult drug;
  final bool isChecked;
  final VoidCallback onToggle;

  const _DrugRow(
      {required this.drug, required this.isChecked, required this.onToggle});

  @override
  Widget build(BuildContext context) {
    return Row(children: [
      Checkbox(value: isChecked, onChanged: (_) => onToggle()),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(drug.displayName,
              style: const TextStyle(fontWeight: FontWeight.w500)),
          if (drug.className != null)
            Text(drug.className!,
                style: TextStyle(fontSize: 12, color: Colors.grey.shade600)),
        ]),
      ),
    ]);
  }
}
