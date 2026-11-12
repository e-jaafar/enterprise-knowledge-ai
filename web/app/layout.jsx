import "./styles.css";

export const metadata = {
  title: "Enterprise Knowledge AI",
  description: "Interrogez vos PDF et vérifiez les pages sources.",
};

export default function Layout({ children }) {
  return (
    <html lang="fr">
      <body>{children}</body>
    </html>
  );
}
