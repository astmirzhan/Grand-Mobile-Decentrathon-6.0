/// Correct Kazakh case affix for a value inserted at runtime.
///
/// A hard-coded affix after a placeholder (`{name}-ға`) is wrong for half of the
/// values, because the affix depends on the last sound of the value. Inflect the
/// value in code and pass the result to the localized string instead:
///
/// ```dart
/// kkInflect('Айдос', KkCase.dative);   // Айдосқа
/// kkInflect('Әлия', KkCase.dative);    // Әлияға
/// kkInflect('100', KkCase.dative);     // 100-ге  (жүз)
/// kkInflect('Google', KkCase.dative);  // Google-ға
/// ```
///
/// Port of `locqa/lang/kk_runtime.py`; both are checked on `test/vectors.json`.
library kk_affix;

enum KkCase { dative, locative, ablative, genitive, accusative, instrumental, plural }

const _back = 'аоұыуяё';
const _front = 'әөүіеи';
const _sonorants = 'рйу';
const _nasals = 'мнң';
const _voiced = 'злж';

// case -> sound class -> [back, front]
const Map<KkCase, Map<String, List<String>>> _affixes = {
  KkCase.plural: {
    'vowel': ['лар', 'лер'], 'sonorant': ['лар', 'лер'], 'nasal': ['дар', 'дер'],
    'voiced': ['дар', 'дер'], 'voiceless': ['тар', 'тер'],
  },
  KkCase.genitive: {
    'vowel': ['ның', 'нің'], 'sonorant': ['дың', 'дің'], 'nasal': ['ның', 'нің'],
    'voiced': ['дың', 'дің'], 'voiceless': ['тың', 'тің'],
  },
  KkCase.accusative: {
    'vowel': ['ны', 'ні'], 'sonorant': ['ды', 'ді'], 'nasal': ['ды', 'ді'],
    'voiced': ['ды', 'ді'], 'voiceless': ['ты', 'ті'],
  },
  KkCase.dative: {
    'vowel': ['ға', 'ге'], 'sonorant': ['ға', 'ге'], 'nasal': ['ға', 'ге'],
    'voiced': ['ға', 'ге'], 'voiceless': ['қа', 'ке'],
  },
  KkCase.locative: {
    'vowel': ['да', 'де'], 'sonorant': ['да', 'де'], 'nasal': ['да', 'де'],
    'voiced': ['да', 'де'], 'voiceless': ['та', 'те'],
  },
  KkCase.ablative: {
    'vowel': ['дан', 'ден'], 'sonorant': ['дан', 'ден'], 'nasal': ['нан', 'нен'],
    'voiced': ['дан', 'ден'], 'voiceless': ['тан', 'тен'],
  },
  KkCase.instrumental: {
    'vowel': ['мен', 'мен'], 'sonorant': ['мен', 'мен'], 'nasal': ['мен', 'мен'],
    'voiced': ['бен', 'бен'], 'voiceless': ['пен', 'пен'], 'l': ['мен', 'мен'],
  },
};

const _units = ['нөл', 'бір', 'екі', 'үш', 'төрт', 'бес', 'алты', 'жеті', 'сегіз', 'тоғыз'];
const _tens = ['', 'он', 'жиырма', 'отыз', 'қырық', 'елу', 'алпыс', 'жетпіс', 'сексен', 'тоқсан'];

const Map<String, String> _latin = {
  'a': 'а', 'ä': 'ә', 'b': 'б', 'c': 'к', 'd': 'д', 'e': 'е', 'f': 'ф', 'g': 'г', 'ğ': 'ғ',
  'h': 'һ', 'i': 'и', 'ı': 'ы', 'j': 'ж', 'k': 'к', 'l': 'л', 'm': 'м', 'n': 'н', 'ñ': 'ң',
  'o': 'о', 'ö': 'ө', 'p': 'п', 'q': 'қ', 'r': 'р', 's': 'с', 'ş': 'ш', 't': 'т', 'u': 'у',
  'ū': 'ұ', 'ü': 'ү', 'v': 'в', 'w': 'у', 'x': 'х', 'y': 'и', 'z': 'з',
};
const _latinConsonants = 'bcdfghjklmnpqrstvwxz';

final _trailingNumber = RegExp(r'(\d+)(?:[.,]\d+)?$');
final _fraction = RegExp(r'[.,](\d+)$');
final _letters = RegExp(r'\p{L}+', unicode: true);
const _trailingPunct = '.,!?:;)»"\'';

/// The spoken word that ends the number: 5 -> бес, 40 -> қырық, 100 -> жүз.
String kkNumberWord(int n) {
  if (n == 0) return _units[0];
  if (n % 10 != 0) return _units[n % 10];
  if (n % 100 != 0) return _tens[(n % 100) ~/ 10];
  if (n % 1000 != 0) return 'жүз';
  if (n % 1000000 != 0) return 'мың';
  if (n % 1000000000 != 0) return 'миллион';
  return 'миллиард';
}

String _rstrip(String s, String chars) {
  var end = s.length;
  while (end > 0 && chars.contains(s[end - 1])) {
    end--;
  }
  return s.substring(0, end);
}

/// Lowercase Cyrillic form of how the value ends when read aloud.
String kkSpokenTail(String value) {
  final v = _rstrip(value.trim(), _trailingPunct).trim();
  final m = _trailingNumber.firstMatch(v);
  if (m != null) {
    final frac = _fraction.firstMatch(v);
    return kkNumberWord(int.parse(frac != null ? frac.group(1)! : m.group(1)!));
  }
  final words = _letters.allMatches(v).toList();
  if (words.isEmpty) return 'а';
  var w = words.last.group(0)!.toLowerCase();
  if (w.split('').every(_latin.containsKey)) {
    // Silent final e in English names: Google, Apple are read гугл, эппл.
    if (w.length > 2 && w.endsWith('e') && _latinConsonants.contains(w[w.length - 2])) {
      w = w.substring(0, w.length - 1);
    }
    w = w.split('').map((ch) => _latin[ch]!).join();
  }
  final tail = _rstrip(w, 'ьъ');
  return tail.isEmpty ? 'а' : tail;
}

String _soundClass(String ch, KkCase c) {
  if (ch == 'л' && c == KkCase.instrumental) return 'l';
  if (_back.contains(ch) || _front.contains(ch)) return 'vowel';
  if (_sonorants.contains(ch)) return 'sonorant';
  if (_nasals.contains(ch)) return 'nasal';
  if (_voiced.contains(ch)) return 'voiced';
  return 'voiceless';
}

bool _isFront(String word) {
  for (var i = word.length - 1; i >= 0; i--) {
    if (_front.contains(word[i])) return true;
    if (_back.contains(word[i])) return false;
  }
  return false;
}

/// Affix only: kkAffix('Айдос', KkCase.dative) == 'қа'.
String kkAffix(String value, KkCase c) {
  final w = kkSpokenTail(value);
  final last = w.isEmpty ? 'а' : w[w.length - 1];
  final pair = _affixes[c]![_soundClass(last, c)]!;
  return _isFront(w) ? pair[1] : pair[0];
}

bool _needsHyphen(String value) {
  final v = value.trim();
  if (v.isEmpty) return false;
  final last = v[v.length - 1];
  return RegExp(r'\d').hasMatch(last) || _latin.containsKey(last.toLowerCase());
}

bool _isUpper(String s) =>
    s.toUpperCase() == s && s.toLowerCase() != s && !RegExp(r'^\d+$').hasMatch(s);

/// Value with the correct affix: kkInflect('Әлия', KkCase.dative) == 'Әлияға'.
String kkInflect(String value, KkCase c) {
  var a = kkAffix(value, c);
  if (_isUpper(value.trim())) a = a.toUpperCase();
  return '$value${_needsHyphen(value) ? '-' : ''}$a';
}
