import createMiddleware from 'next-intl/middleware';

export default createMiddleware({
  // Lista de locales soportados
  locales: ['en', 'es'],
  
  // Locale por defecto
  defaultLocale: 'es',
  
  // Redirigir a la URL con locale
  localePrefix: 'always'
});

export const config = {
  // Matcher configurado para manejar todos los paths excepto los que comienzan con
  // /api/, /_next/, /_vercel/, /images/, /favicon.ico, /robots.txt
  matcher: ['/((?!api|_next|_vercel|images|favicon.ico|robots.txt).*)']
};
