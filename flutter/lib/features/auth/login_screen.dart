import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/brand_mark.dart';
import 'auth_provider.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _emailCtrl = TextEditingController();
  final _pwCtrl = TextEditingController();
  bool _obscurePw = true;

  @override
  void dispose() {
    _emailCtrl.dispose();
    _pwCtrl.dispose();
    super.dispose();
  }

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
          body: SafeArea(
            child: LayoutBuilder(
              builder: (context, c) => SingleChildScrollView(
                padding: const EdgeInsets.symmetric(horizontal: 24),
                child: ConstrainedBox(
                  constraints: BoxConstraints(minHeight: c.maxHeight),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const BrandMark(),
                      Gap.v32,
                      TextField(
                        controller: _emailCtrl,
                        decoration: const InputDecoration(
                          labelText: '이메일',
                          prefixIcon: Icon(Icons.mail_outline_rounded),
                        ),
                        keyboardType: TextInputType.emailAddress,
                        textInputAction: TextInputAction.next,
                      ),
                      Gap.v12,
                      TextField(
                        controller: _pwCtrl,
                        decoration: InputDecoration(
                          labelText: '비밀번호',
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
                        onSubmitted: (_) =>
                            auth.login(_emailCtrl.text, _pwCtrl.text),
                      ),
                      if (auth.status == AuthStatus.error) ...[
                        Gap.v12,
                        _ErrorText(auth.errorMessage ?? '로그인에 실패했습니다.'),
                      ],
                      Gap.v24,
                      FilledButton(
                        onPressed: loading
                            ? null
                            : () => auth.login(_emailCtrl.text, _pwCtrl.text),
                        child: loading
                            ? const SizedBox(
                                height: 20,
                                width: 20,
                                child: CircularProgressIndicator(
                                    strokeWidth: 2, color: Colors.white))
                            : const Text('로그인'),
                      ),
                      Gap.v8,
                      TextButton(
                        onPressed: () => context.push('/register'),
                        child: Text.rich(TextSpan(
                          text: '계정이 없으신가요?  ',
                          style: TextStyle(color: scheme.onSurfaceVariant),
                          children: const [
                            TextSpan(
                              text: '회원가입',
                              style: TextStyle(fontWeight: FontWeight.w700),
                            ),
                          ],
                        )),
                      ),
                      Gap.v24,
                      Text(
                        '식품의약품안전처·공공데이터포털의 공공데이터를 활용합니다.\n'
                        '병용 위험 정보는 참고용이며 의학적 진단이 아닙니다.',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                            fontSize: 11,
                            height: 1.4,
                            color: scheme.onSurfaceVariant),
                      ),
                      Gap.v16,
                    ],
                  ),
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

class _ErrorText extends StatelessWidget {
  final String message;
  const _ErrorText(this.message);

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: scheme.errorContainer,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(children: [
        Icon(Icons.error_outline_rounded,
            size: 18, color: scheme.onErrorContainer),
        const SizedBox(width: 8),
        Expanded(
          child: Text(message,
              style: TextStyle(fontSize: 13, color: scheme.onErrorContainer)),
        ),
      ]),
    );
  }
}
