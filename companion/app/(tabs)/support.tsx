import { Link } from 'expo-router';
import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';

const supportItems = [
  {
    id: 'cod-9',
    title: 'AI Avatar Chat',
    description: 'Single-page chat with a friendly avatar response.',
    href: '/support/ai-avatar-chat',
  },
  {
    id: 'cod-10',
    title: 'Model Selector Input',
    description: 'Add a model selector inside the input box for gpt5.2.',
    href: '/support/model-selector',
  },
];

export default function SupportScreen() {
  return (
    <ThemedView style={styles.container}>
      <ThemedView style={styles.header}>
        <ThemedText type="title">Support</ThemedText>
        <ThemedText type="subtitle">Active builds</ThemedText>
      </ThemedView>
      <View style={styles.list}>
        {supportItems.map((item) => (
          <Link key={item.id} href={item.href} asChild>
            <Pressable style={styles.card}>
              <ThemedText type="defaultSemiBold">{item.title}</ThemedText>
              <ThemedText style={styles.cardDescription}>{item.description}</ThemedText>
              <ThemedText style={styles.cardLink}>Open</ThemedText>
            </Pressable>
          </Link>
        ))}
      </View>
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 20,
    gap: 16,
  },
  header: {
    gap: 6,
  },
  list: {
    gap: 12,
  },
  card: {
    borderRadius: 16,
    padding: 16,
    gap: 8,
    borderWidth: 1,
    borderColor: 'rgba(0,0,0,0.08)',
  },
  cardDescription: {
    opacity: 0.7,
  },
  cardLink: {
    opacity: 0.6,
  },
});
