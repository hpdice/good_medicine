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
      return Scaffold(
        appBar: AppBar(
          title: const Text('OCR 결과'),
          leading: IconButton(
            icon: const Icon(Icons.arrow_back),
            onPressed: () => context.pop(),
          ),
        ),
        bottomNavigationBar: SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              if (_checked.isNotEmpty) ...[
                FilledButton(
                  onPressed: () {
                    final ids = _checked.toList();
                    context.go('/');
                    cam.addDrugsToBox(ids);
                  },
                  child: Text('내 약에 추가 (${_checked.length}개)'),
                ),
                const SizedBox(height: 8),
              ],
              OutlinedButton.icon(
                onPressed: () => context.go('/search'),
                icon: const Icon(Icons.search, size: 18),
                label: const Text('인식 안 된 약은 직접 검색으로 추가'),
                style: OutlinedButton.styleFrom(
                    minimumSize: const Size.fromHeight(44)),
              ),
            ]),
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
    if (cam.isProcessing == false && cam.matchResults.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.search_off, size: 48, color: Colors.grey),
            const SizedBox(height: 16),
            const Text('약품명을 자동으로 인식하지 못했습니다.',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 16)),
            const SizedBox(height: 8),
            Text('사진 각도나 조명을 바꿔 다시 시도하거나\n아래 버튼으로 직접 검색해 주세요.',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 13, color: Colors.grey.shade600)),
            const SizedBox(height: 24),
            FilledButton.icon(
              onPressed: () => context.go('/search'),
              icon: const Icon(Icons.search),
              label: const Text('직접 검색으로 추가'),
            ),
          ]),
        ),
      );
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
