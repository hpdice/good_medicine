import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../core/theme/app_theme.dart';
import '../auth/auth_provider.dart';
import '../home/home_provider.dart';
import 'profile_provider.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  final _birthYearCtrl = TextEditingController();
  List<String> _healthConditions = [];
  List<String> _allergyInfo = [];
  bool _isPregnant = false;
  bool _loadedOnce = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final provider = context.read<ProfileProvider>();
      await provider.load();
      _syncFromProfile(provider);
    });
  }

  void _syncFromProfile(ProfileProvider provider) {
    final profile = provider.profile;
    if (profile == null || _loadedOnce) return;
    setState(() {
      _healthConditions = [...profile.healthConditions];
      _allergyInfo = [...profile.allergyInfo];
      _birthYearCtrl.text = profile.birthYear?.toString() ?? '';
      _isPregnant = profile.isPregnant ?? false;
      _loadedOnce = true;
    });
  }

  @override
  void dispose() {
    _birthYearCtrl.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final provider = context.read<ProfileProvider>();
    int? birthYear;
    final text = _birthYearCtrl.text.trim();
    if (text.isNotEmpty) {
      birthYear = int.tryParse(text);
      final thisYear = DateTime.now().year;
      if (birthYear == null || birthYear < 1900 || birthYear > thisYear) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('출생연도를 올바르게 입력해 주세요.')),
        );
        return;
      }
    }
    final ok = await provider.save(
      healthConditions: _healthConditions,
      allergyInfo: _allergyInfo,
      birthYear: birthYear,
      isPregnant: _isPregnant,
    );
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(ok ? '저장했습니다.' : (provider.error ?? '저장 실패'))),
    );
  }

  Future<void> _logout() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('로그아웃'),
        content: const Text('로그아웃할까요?'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('취소')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('로그아웃')),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    // 로그아웃하면 라우터가 이 화면을 걷어내므로, provider는 먼저 꺼내 둔다.
    final auth = context.read<AuthProvider>();
    final profile = context.read<ProfileProvider>();
    final home = context.read<HomeProvider>();
    await auth.logout();
    profile.clear();
    await home.clear();
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<ProfileProvider>(builder: (context, provider, _) {
      _syncFromProfile(provider);
      final loading = provider.status == ProfileStatus.loading && !_loadedOnce;
      final saving = provider.status == ProfileStatus.saving;

      return Scaffold(
        appBar: AppBar(title: const Text('내 정보')),
        body: loading
            ? const Center(child: CircularProgressIndicator())
            : SafeArea(
                child: SingleChildScrollView(
                  padding: kScreenPadding,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text('출생연도',
                          style: Theme.of(context)
                              .textTheme
                              .titleMedium
                              ?.copyWith(fontWeight: FontWeight.w700)),
                      Gap.v4,
                      Text(
                        '특정연령대금기·노인주의 등 연령 기반 DUR 규칙 확인에 사용됩니다. '
                        '본인이 아니라 자녀·부모님 등 실제 복약 대상의 나이를 입력해도 됩니다. '
                        '선택 입력이며, 비워두면 연령 기반 판정만 건너뜁니다.',
                        style: TextStyle(
                            fontSize: 12.5,
                            color: Theme.of(context).colorScheme.onSurfaceVariant,
                            height: 1.4),
                      ),
                      Gap.v8,
                      TextField(
                        controller: _birthYearCtrl,
                        keyboardType: TextInputType.number,
                        decoration: const InputDecoration(
                          labelText: '출생연도 (예: 1990)',
                          prefixIcon: Icon(Icons.cake_outlined),
                        ),
                      ),
                      Gap.v16,
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        title: Text('임신 중',
                            style: Theme.of(context)
                                .textTheme
                                .titleMedium
                                ?.copyWith(fontWeight: FontWeight.w700)),
                        subtitle: Text(
                          '켜면 복약함 약 중 DUR 임부금기에 해당하는 약을 경고합니다. '
                          '보호자가 복약 대상 대신 입력해도 됩니다. 이 정보는 암호화되어 저장됩니다.',
                          style: TextStyle(
                              fontSize: 12.5,
                              color: Theme.of(context).colorScheme.onSurfaceVariant,
                              height: 1.4),
                        ),
                        value: _isPregnant,
                        onChanged: (v) => setState(() => _isPregnant = v),
                      ),
                      Gap.v24,
                      _ChipListEditor(
                        title: '건강 상태',
                        description: 'AI 대응 가이드 생성 시 참고 정보로 사용됩니다.',
                        hintText: '예: 고혈압',
                        items: _healthConditions,
                        onChanged: (v) => setState(() => _healthConditions = v),
                      ),
                      Gap.v24,
                      _ChipListEditor(
                        title: '알레르기',
                        description: '등록한 성분과 겹치는 약을 추가하면 즉시 경고합니다.',
                        hintText: '예: 페니실린',
                        items: _allergyInfo,
                        onChanged: (v) => setState(() => _allergyInfo = v),
                      ),
                      if (provider.status == ProfileStatus.error) ...[
                        Gap.v12,
                        Text(provider.error ?? '오류가 발생했습니다.',
                            style: TextStyle(
                                color: Theme.of(context).colorScheme.error,
                                fontSize: 13)),
                      ],
                      Gap.v24,
                      FilledButton(
                        onPressed: saving ? null : _save,
                        child: saving
                            ? const SizedBox(
                                height: 20,
                                width: 20,
                                child: CircularProgressIndicator(
                                    strokeWidth: 2, color: Colors.white))
                            : const Text('저장'),
                      ),
                      Gap.v12,
                      OutlinedButton.icon(
                        onPressed: saving ? null : _logout,
                        icon: const Icon(Icons.logout_rounded),
                        label: const Text('로그아웃'),
                      ),
                    ],
                  ),
                ),
              ),
      );
    });
  }
}

/// 자유 텍스트 목록(건강 상태·알레르기)을 칩으로 편집하는 위젯.
class _ChipListEditor extends StatefulWidget {
  final String title;
  final String description;
  final String hintText;
  final List<String> items;
  final ValueChanged<List<String>> onChanged;

  const _ChipListEditor({
    required this.title,
    required this.description,
    required this.hintText,
    required this.items,
    required this.onChanged,
  });

  @override
  State<_ChipListEditor> createState() => _ChipListEditorState();
}

class _ChipListEditorState extends State<_ChipListEditor> {
  final _ctrl = TextEditingController();

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  void _add() {
    final v = _ctrl.text.trim();
    if (v.isEmpty || widget.items.contains(v)) return;
    widget.onChanged([...widget.items, v]);
    _ctrl.clear();
  }

  void _remove(String v) {
    widget.onChanged(widget.items.where((e) => e != v).toList());
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(widget.title,
          style: Theme.of(context)
              .textTheme
              .titleMedium
              ?.copyWith(fontWeight: FontWeight.w700)),
      Gap.v4,
      Text(widget.description,
          style: TextStyle(
              fontSize: 12.5, color: scheme.onSurfaceVariant, height: 1.4)),
      Gap.v8,
      Row(children: [
        Expanded(
          child: TextField(
            controller: _ctrl,
            decoration: InputDecoration(hintText: widget.hintText),
            onSubmitted: (_) => _add(),
          ),
        ),
        const SizedBox(width: 8),
        IconButton.filledTonal(
          icon: const Icon(Icons.add_rounded),
          onPressed: _add,
        ),
      ]),
      if (widget.items.isNotEmpty) ...[
        Gap.v8,
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final v in widget.items)
              Chip(
                label: Text(v),
                onDeleted: () => _remove(v),
              ),
          ],
        ),
      ],
    ]);
  }
}
