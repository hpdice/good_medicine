import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../../core/theme/app_theme.dart';
import 'auth_provider.dart';

class RegisterScreen extends StatefulWidget {
  const RegisterScreen({super.key});

  @override
  State<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends State<RegisterScreen> {
  final _nameCtrl = TextEditingController();
  final _emailCtrl = TextEditingController();
  final _pwCtrl = TextEditingController();
  bool _obscurePw = true;
  bool _privacyConsent = false;
  bool _healthConsent = false;

  @override
  void dispose() {
    _nameCtrl.dispose();
    _emailCtrl.dispose();
    _pwCtrl.dispose();
    super.dispose();
  }

  bool get _canSubmit =>
      _nameCtrl.text.isNotEmpty &&
      _emailCtrl.text.isNotEmpty &&
      _pwCtrl.text.length >= 8 &&
      _privacyConsent &&
      _healthConsent;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Consumer<AuthProvider>(
      builder: (context, auth, _) {
        if (auth.status == AuthStatus.success) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            auth.resetState();
            context.go('/');
          });
        }
        final loading = auth.status == AuthStatus.loading;
        return Scaffold(
          appBar: AppBar(title: const Text('회원가입')),
          body: SafeArea(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(24, 8, 24, 32),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  TextField(
                    controller: _nameCtrl,
                    decoration: const InputDecoration(
                      labelText: '이름',
                      prefixIcon: Icon(Icons.person_outline_rounded),
                    ),
                    textInputAction: TextInputAction.next,
                    onChanged: (_) => setState(() {}),
                  ),
                  Gap.v12,
                  TextField(
                    controller: _emailCtrl,
                    decoration: const InputDecoration(
                      labelText: '이메일',
                      prefixIcon: Icon(Icons.mail_outline_rounded),
                    ),
                    keyboardType: TextInputType.emailAddress,
                    textInputAction: TextInputAction.next,
                    onChanged: (_) => setState(() {}),
                  ),
                  Gap.v12,
                  TextField(
                    controller: _pwCtrl,
                    decoration: InputDecoration(
                      labelText: '비밀번호 (8자 이상)',
                      prefixIcon: const Icon(Icons.lock_outline_rounded),
                      suffixIcon: IconButton(
                        icon: Icon(_obscurePw
                            ? Icons.visibility_off_outlined
                            : Icons.visibility_outlined),
                        tooltip: _obscurePw ? '비밀번호 표시' : '비밀번호 숨기기',
                        onPressed: () =>
                            setState(() => _obscurePw = !_obscurePw),
                      ),
                    ),
                    obscureText: _obscurePw,
                    onChanged: (_) => setState(() {}),
                  ),
                  Gap.v16,
                  _ConsentTile(
                    value: _privacyConsent,
                    label: '개인정보 수집 및 이용 동의 (필수)',
                    onChanged: (v) => setState(() => _privacyConsent = v),
                  ),
                  _ConsentTile(
                    value: _healthConsent,
                    label: '건강 정보 처리 동의 (필수)',
                    onChanged: (v) => setState(() => _healthConsent = v),
                  ),
                  if (auth.status == AuthStatus.error) ...[
                    Gap.v12,
                    Text(auth.errorMessage ?? '회원가입에 실패했습니다.',
                        style: TextStyle(color: scheme.error, fontSize: 13)),
                  ],
                  Gap.v24,
                  FilledButton(
                    onPressed: loading || !_canSubmit
                        ? null
                        : () => auth.register(
                            _emailCtrl.text, _pwCtrl.text, _nameCtrl.text),
                    child: loading
                        ? const SizedBox(
                            height: 20,
                            width: 20,
                            child: CircularProgressIndicator(
                                strokeWidth: 2, color: Colors.white))
                        : const Text('회원가입'),
                  ),
                  Gap.v8,
                  TextButton(
                    onPressed: () => context.pop(),
                    child: const Text('로그인으로 돌아가기'),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}

class _ConsentTile extends StatelessWidget {
  final bool value;
  final String label;
  final ValueChanged<bool> onChanged;

  const _ConsentTile({
    required this.value,
    required this.label,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: () => onChanged(!value),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(children: [
          Checkbox(
            value: value,
            onChanged: (v) => onChanged(v ?? false),
            visualDensity: VisualDensity.compact,
            materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
          ),
          const SizedBox(width: 4),
          Expanded(child: Text(label, style: const TextStyle(fontSize: 14))),
        ]),
      ),
    );
  }
}
