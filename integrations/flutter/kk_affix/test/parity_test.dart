// Checks the Dart port against the vectors generated from the Python reference.
// Run: dart run test/parity_test.dart
import 'dart:convert';
import 'dart:io';

import 'package:kk_affix/kk_affix.dart';

void main() {
  final file = File.fromUri(Platform.script.resolve('vectors.json'));
  final vectors = jsonDecode(file.readAsStringSync()) as List<dynamic>;
  var failed = 0;
  for (final v in vectors) {
    final c = KkCase.values.byName(v['case'] as String);
    final got = kkInflect(v['value'] as String, c);
    if (got != v['expected']) {
      failed++;
      stderr.writeln('${v['value']} ${v['case']}: expected ${v['expected']}, got $got');
    }
  }
  stdout.writeln('${vectors.length - failed}/${vectors.length} vectors match');
  exit(failed == 0 ? 0 : 1);
}
