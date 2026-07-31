/* Minimal probe header for the SDL3 macro-support survey (Part A / B4).
 *
 * Each `P_*` macro isolates one C construct. Each `C_*` control differs from its
 * probe only in that construct, so a failing probe with a passing control
 * attributes the failure to the construct rather than to its surroundings
 * (parentheses in particular: the parser reports `unexpected "("` at the start of
 * the failing production, not at the offending token).
 *
 * Self-contained on purpose: no #include, so the frontend dump contains only
 * these macros.
 */

typedef unsigned long probe_size_t;

struct probe_s { int a; int b; };

/* --- controls: these must all succeed ------------------------------------- */

#define C_PARENS(x)        ((x) + 1)
#define C_NESTED_PARENS(x) (((x)))
#define C_ARITH(x, y)      ((x) + (y) * 2)
#define C_RELATIONAL(x, y) ((x) < (y))
#define C_SHIFT(x, n)      ((x) << (n))
#define C_BITWISE(x, y)    (((x) & (y)) | ((x) ^ (y)))
#define C_LOGICAL(x, y)    ((x) && (y) || !(x))
#define C_UNARY(x)         (-(x) + +(x) + ~(x))
#define C_STR              "a"
#define C_CHAR             'a'
#define C_TYPE_KW          unsigned int
#define C_TYPE_PTR         const int *const
#define C_TYPE_TAGGED      struct probe_s
#define C_TYPE_TYPEDEF     probe_size_t

/* --- conditional --------------------------------------------------------- */

#define P_TERN(x, y)       ((x) < (y) ? (x) : (y))
#define P_TERN_BARE        1 ? 2 : 3

/* --- cast ---------------------------------------------------------------- */

#define P_CAST_KW(x)       ((int)(x))
#define P_CAST_KW_MULTI(x) ((unsigned int)(x))
#define P_CAST_TYPEDEF(x)  ((probe_size_t)(x))
#define P_CAST_PTR(x)      ((int *)(x))
/* The SDL_static_cast shape: the cast target is a macro parameter. */
#define P_CAST_PARAM(t, x) ((t)(x))

/* --- sizeof / alignof / offsetof ----------------------------------------- */

#define P_SIZEOF_EXPR(x)   sizeof(x)
#define P_SIZEOF_TYPE      sizeof(int)
#define P_ALIGNOF          _Alignof(int)
#define P_OFFSETOF         __builtin_offsetof(struct probe_s, b)

/* --- preprocessor operators ---------------------------------------------- */

#define P_STRINGIFY(x)     #x
#define P_PASTE(a, b)      a##b

/* --- function call ------------------------------------------------------- */

/* Callee is a free identifier: expected to parse (Var with actual args). */
#define P_CALL_FREE(x)     probe_fn(x)
/* Callee is a macro parameter: no production for this. */
#define P_CALL_PARAM(f, x) f(x)
/* Callee is another macro. */
#define P_CALL_MACRO(x)    C_PARENS(x)

/* --- assignment ---------------------------------------------------------- */

#define P_ASSIGN(x)        ((x) = 1)
#define P_ASSIGN_COMPOUND(x) ((x) += 1)

/* --- statement expression / do-while ------------------------------------- */

#define P_STMT_EXPR(x)     ({ int t_ = (x); t_; })
#define P_DO_WHILE(x)      do { probe_fn(x); } while (0)

/* --- comma operator ------------------------------------------------------ */

/* NB: expected to *succeed* but be mis-typed as a tuple (see
   https://github.com/well-typed/hs-bindgen/issues/2182). */
#define P_COMMA(x, y)      ((x), (y))
#define P_COMMA_BARE(x, y) (x), (y)

/* --- type in parameter position ------------------------------------------ */

/* Parses (body is a type literal), but cannot typecheck: the parameter is
 * unused and the result is a type, not a value. */
#define P_TYPE_BODY(t)     int

/* --- compound literal / designated initialiser --------------------------- */

#define P_COMPOUND_LIT(x)  ((struct probe_s){ (x), 0 })
#define P_DESIGNATED(x)    ((struct probe_s){ .a = (x) })

/* --- member access / subscript / address-of / dereference ---------------- */

#define P_DOT(s)           ((s).a)
#define P_ARROW(p)         ((p)->a)
#define P_SUBSCRIPT(a, i)  ((a)[(i)])
#define P_ADDR_OF(x)       (&(x))
#define P_DEREF(p)         (*(p))

/* --- _Generic ------------------------------------------------------------ */

#define P_GENERIC(x)       _Generic((x), int: 1, default: 0)

/* --- variadic macros ----------------------------------------------------- */

#define P_VA_ARGS(...)     probe_fn(__VA_ARGS__)
#define P_VA_NAMED(a, ...) probe_fn(a, __VA_ARGS__)

/* --- string literal concatenation ---------------------------------------- */

#define P_STR_CONCAT       "a" "b"

/* --- attributes / builtins ----------------------------------------------- */

#define P_ATTRIBUTE        __attribute__((packed))
#define P_BUILTIN(x)       __builtin_expect((x), 0)

/* --- increment / decrement ----------------------------------------------- */

#define P_POST_INCR(x)     ((x)++)
#define P_PRE_INCR(x)      (++(x))
