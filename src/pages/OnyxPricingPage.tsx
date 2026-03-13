// src/pages/OnyxPricingPage.tsx
import React from 'react';

// 1) Crypto receive addresses (your wallets)
const CRYPTO_ADDRESSES = {
  ethEvm: '0x59e7778EB7c28ea6Eb2fE1a06fF693A04E9535Eb', // EVM (ETH, USDT, etc.)
  btc: 'bc1p6a9de8md64psxdmu6cjstfzqrxr0rxyxgtyj5293aajlrkpua2ns84ggpr', // Bitcoin
  solanaLike: 'BTyjtayJJNguYoBpVDMfrBJgZ25vVZsG96TYwJLf7Wi3', // Phantom/Solana-style
};

// 2) Pricing tiers (using your existing Stripe Payment Links)
const tiers = [
  {
    id: 'basic',
    name: 'Onyx AI Basic',
    price: '$11.98',
    period: 'per month',
    stripeLink:
      'https://dashboard.stripe.com/acct_1SiHqC2KmpnVwTx7/payment-links/plink_1SiOvb2KmpnVwTx7bwHGn1x7', // 11.98/m
    description: 'Core AI + dashboards for individuals.',
    features: ['1 workspace', 'Standard ONYX inference', 'Email support'],
  },
  {
    id: 'starter-miner',
    name: 'Onyx Miner Starter',
    price: '$19.99',
    period: 'per month',
    stripeLink:
      'https://dashboard.stripe.com/acct_1SiHqC2KmpnVwTx7/payment-links/plink_1SiMJM2KmpnVwTx7zDs50L6O', // 19.99/m
    description: 'Entry access to ONYX mining & dashboard.',
    features: ['ONYX Mining Dashboard access', 'Base mining rate'],
    minerTier: true,
  },
  {
    id: 'elite-miner',
    name: 'Elite ONYX Miner',
    price: '$198',
    period: 'per month',
    stripeLink:
      'https://dashboard.stripe.com/acct_1SiHqC2KmpnVwTx7/payment-links/plink_1SiOxU2KmpnVwTx76cxN728h', // 198/m
    description: 'Elite mining tier with maxed-out perks.',
    features: [
      'Full ONYX Mining Dashboard',
      'Boosted mining rate',
      'Priority support',
      'Elite-only features & drops',
    ],
    highlighted: true,
    minerTier: true,
  },
  {
    id: 'plus',
    name: 'Onyx AI Plus',
    price: '$39',
    period: 'one-time',
    stripeLink:
      'https://dashboard.stripe.com/acct_1SiHqC2KmpnVwTx7/payment-links/plink_1SiOwD2KmpnVwTx7tLxc34UA', // 39 one-time
    description: 'One-time unlock for extra tools.',
    features: ['Extra tools & models', 'Priority queue'],
  },
];

export const OnyxPricingPage: React.FC = () => {
  const [cryptoTier, setCryptoTier] = React.useState<string | null>(null);

  const handleStripeCheckout = (tierId: string) => {
    const tier = tiers.find(t => t.id === tierId);
    if (!tier?.stripeLink) return;
    // Opens Stripe Payment Link (cards + Apple Pay + Link if enabled in Stripe)
    window.open(tier.stripeLink, '_blank');
  };

  const handleCryptoCheckout = (tierId: string) => {
    setCryptoTier(tierId); // open crypto modal for that tier
  };

  const handleLinkCheckout = (tierId: string) => {
    // If later you use Stripe Checkout instead of Payment Links, Link is handled by Stripe.
    console.log('link checkout', tierId);
  };

  const closeCryptoModal = () => setCryptoTier(null);

  const activeTier = tiers.find(t => t.id === cryptoTier);

  return (
    <div
      style={{
        minHeight: '100vh',
        background: 'radial-gradient(circle at top, #020617 0, #000000 55%)',
        color: 'white',
        padding: '40px 20px',
      }}
    >
      <div style={{ maxWidth: 1080, margin: '0 auto' }}>
        <header style={{ textAlign: 'center', marginBottom: 40 }}>
          <h1 style={{ fontSize: 40, marginBottom: 12 }}>ONYX AI Platform Pricing</h1>
          <p style={{ opacity: 0.8 }}>
            Choose your **ONYX** plan. Pay with card, Apple Pay, Link, or crypto.
          </p>
        </header>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
            gap: 24,
          }}
        >
          {tiers.map(tier => (
            <div
              key={tier.id}
              style={{
                borderRadius: 16,
                padding: 24,
                background:
                  tier.highlighted
                    ? 'linear-gradient(135deg, #22c55e 0%, #16a34a 40%, #15803d 100%)'
                    : 'linear-gradient(145deg, rgba(148,163,184,0.16), rgba(15,23,42,0.9))',
                boxShadow: tier.highlighted
                  ? '0 18px 45px rgba(34,197,94,0.6)'
                  : '0 12px 30px rgba(15,23,42,0.85)',
                border: tier.highlighted ? '1px solid rgba(34,197,94,0.6)' : '1px solid rgba(148,163,184,0.3)',
              }}
            >
              <div style={{ marginBottom: 16 }}>
                <h2 style={{ fontSize: 22, marginBottom: 6 }}>{tier.name}</h2>
                <p style={{ opacity: 0.8, fontSize: 14 }}>{tier.description}</p>
              </div>

              <div style={{ marginBottom: 16 }}>
                <span style={{ fontSize: 32, fontWeight: 700 }}>{tier.price}</span>
                {tier.period && (
                  <span style={{ marginLeft: 6, opacity: 0.8, fontSize: 14 }}>
                    {tier.period}
                  </span>
                )}
              </div>

              <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 20px 0', fontSize: 14 }}>
                {tier.features.map(f => (
                  <li key={f} style={{ marginBottom: 6 }}>
                    • {f}
                  </li>
                ))}
              </ul>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <button
                  onClick={() => handleStripeCheckout(tier.id)}
                  style={{
                    padding: '10px 14px',
                    borderRadius: 999,
                    border: 'none',
                    cursor: 'pointer',
                    backgroundColor: '#635bff',
                    color: 'white',
                    fontWeight: 600,
                  }}
                >
                  Pay with Card / Apple Pay / Link
                </button>

                <button
                  onClick={() => handleCryptoCheckout(tier.id)}
                  style={{
                    padding: '10px 14px',
                    borderRadius: 999,
                    border: '1px solid rgba(148,163,184,0.8)',
                    cursor: 'pointer',
                    backgroundColor: 'transparent',
                    color: 'white',
                    fontWeight: 500,
                  }}
                >
                  Pay with Crypto
                </button>
              </div>
            </div>
          ))}
        </div>

        <p style={{ marginTop: 32, fontSize: 12, opacity: 0.65, textAlign: 'center' }}>
          Stripe Payment Links handle cards, Apple Pay, and Link once you enable them in your Stripe Dashboard.
          Crypto payments go directly to your listed wallet addresses.
        </p>
      </div>

      {/* Crypto modal */}
      {cryptoTier && activeTier && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.7)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 9999,
          }}
        >
          <div
            style={{
              background: '#020617',
              borderRadius: 16,
              padding: 24,
              maxWidth: 420,
              width: '90%',
              color: 'white',
              boxShadow: '0 20px 60px rgba(0,0,0,0.8)',
            }}
          >
            <h3 style={{ marginBottom: 8 }}>Pay with Crypto – {activeTier.name}</h3>
            <p style={{ fontSize: 13, opacity: 0.8, marginBottom: 16 }}>
              Send the equivalent of {activeTier.price} in your preferred network to one of these addresses.
              After sending, email your tx hash + wallet to support so we can activate your plan.
            </p>

            <div style={{ fontSize: 13, marginBottom: 10 }}>
              <div style={{ fontWeight: 600 }}>EVM / Ethereum (Metamask, Phantom EVM, etc.)</div>
              <code style={{ wordBreak: 'break-all' }}>{CRYPTO_ADDRESSES.ethEvm}</code>
            </div>

            <div style={{ fontSize: 13, marginBottom: 10 }}>
              <div style={{ fontWeight: 600 }}>Bitcoin (BTC)</div>
              <code style={{ wordBreak: 'break-all' }}>{CRYPTO_ADDRESSES.btc}</code>
            </div>

            <div style={{ fontSize: 13, marginBottom: 16 }}>
              <div style={{ fontWeight: 600 }}>Phantom / Solana-style address</div>
              <code style={{ wordBreak: 'break-all' }}>{CRYPTO_ADDRESSES.solanaLike}</code>
              <div style={{ opacity: 0.75, marginTop: 4 }}>
                Use Phantom Wallet on Solana or compatible chains to send here.
              </div>
            </div>

            <button
              onClick={closeCryptoModal}
              style={{
                marginTop: 8,
                padding: '8px 14px',
                borderRadius: 999,
                border: 'none',
                background: '#22c55e',
                color: '#020617',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default OnyxPricingPage;
