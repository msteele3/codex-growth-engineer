import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Animated,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Image } from 'expo-image';

const OPENAI_API_KEY = process.env.EXPO_PUBLIC_OPENAI_API_KEY;

function TypingDots() {
  const dot1 = useRef(new Animated.Value(0)).current;
  const dot2 = useRef(new Animated.Value(0)).current;
  const dot3 = useRef(new Animated.Value(0)).current;
  const dots = useMemo(() => [dot1, dot2, dot3], [dot1, dot2, dot3]);

  useEffect(() => {
    const animations = dots.map((dot, i) =>
      Animated.loop(
        Animated.sequence([
          Animated.delay(i * 200),
          Animated.timing(dot, { toValue: 1, duration: 300, useNativeDriver: true }),
          Animated.timing(dot, { toValue: 0, duration: 300, useNativeDriver: true }),
        ])
      )
    );
    animations.forEach((a) => a.start());
    return () => animations.forEach((a) => a.stop());
  }, [dots]);

  return (
    <View style={{ flexDirection: 'row', gap: 4, paddingVertical: 4, paddingHorizontal: 2 }}>
      {dots.map((dot, i) => (
        <Animated.View
          key={i}
          style={{
            width: 7,
            height: 7,
            borderRadius: 3.5,
            backgroundColor: '#666',
            opacity: dot.interpolate({ inputRange: [0, 1], outputRange: [0.3, 1] }),
          }}
        />
      ))}
    </View>
  );
}

const SYSTEM_PROMPT = `You are a warm, playful companion. You're cheerful, supportive, and speak casually like a close friend. Keep responses concise (1-3 sentences usually). Use a gentle, encouraging tone. You can be witty and fun but never mean. You genuinely care about the person you're talking to.`;

type Message = {
  role: 'user' | 'assistant';
  content: string;
};

export default function ChatScreen() {
  const insets = useSafeAreaInsets();
  const scrollRef = useRef<ScrollView>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [selectedModel, setSelectedModel] = useState('gpt5.2');

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || loading) return;

    const userMessage: Message = { role: 'user', content: text };
    const updated = [...messages, userMessage];
    setMessages(updated);
    setInput('');
    setLoading(true);

    try {
      const res = await fetch('https://api.openai.com/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${OPENAI_API_KEY}`,
        },
        body: JSON.stringify({
          model: selectedModel,
          messages: [{ role: 'system', content: SYSTEM_PROMPT }, ...updated],
          max_tokens: 256,
        }),
      });

      const data = await res.json();
      const reply = data.choices?.[0]?.message?.content ?? 'Hmm, I got nothing. Try again?';
      setMessages((prev) => [...prev, { role: 'assistant', content: reply }]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: "Sorry, I couldn't connect. Check your internet?" },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={0}
    >
      <View style={[styles.header, { paddingTop: insets.top + 8 }]}>
        <Image
          source={require('@/assets/images/avatar.jpg')}
          style={styles.headerAvatar}
        />
        <Text style={styles.headerTitle}>Companion</Text>
      </View>

      <ScrollView
        ref={scrollRef}
        style={styles.messages}
        contentContainerStyle={styles.messagesContent}
        onContentSizeChange={() => scrollRef.current?.scrollToEnd({ animated: true })}
        keyboardShouldPersistTaps="handled"
      >
        {messages.map((msg, i) => (
          <View
            key={i}
            style={[
              styles.row,
              msg.role === 'user' ? styles.rowUser : styles.rowAssistant,
            ]}
          >
            {msg.role === 'assistant' && (
              <Image
                source={require('@/assets/images/avatar.jpg')}
                style={styles.avatar}
              />
            )}
            <View
              style={[
                styles.bubble,
                msg.role === 'user' ? styles.bubbleUser : styles.bubbleAssistant,
              ]}
            >
              <Text
                style={[
                  styles.bubbleText,
                  msg.role === 'user' ? styles.bubbleTextUser : styles.bubbleTextAssistant,
                ]}
              >
                {msg.content}
              </Text>
            </View>
          </View>
        ))}

        {loading && (
          <View style={[styles.row, styles.rowAssistant]}>
            <Image
              source={require('@/assets/images/avatar.jpg')}
              style={styles.avatar}
            />
            <View style={[styles.bubble, styles.bubbleAssistant]}>
              <TypingDots />
            </View>
          </View>
        )}
      </ScrollView>

      <View style={[styles.inputBar, { paddingBottom: insets.bottom + 8 }]}>
        <View style={styles.modelSelector}>
          <Pressable
            onPress={() => setModelMenuOpen((prev) => !prev)}
            style={styles.modelButton}
          >
            <Text style={styles.modelButtonText}>{selectedModel}</Text>
          </Pressable>
          {modelMenuOpen && (
            <View style={styles.modelMenu}>
              {['gpt5.2', 'gpt-4o-mini', 'gpt-4.1'].map((model) => (
                <Pressable
                  key={model}
                  style={styles.modelMenuItem}
                  onPress={() => {
                    setSelectedModel(model);
                    setModelMenuOpen(false);
                  }}
                >
                  <Text
                    style={[
                      styles.modelMenuText,
                      model === selectedModel && styles.modelMenuTextActive,
                    ]}
                  >
                    {model}
                  </Text>
                </Pressable>
              ))}
            </View>
          )}
        </View>
        <TextInput
          style={styles.input}
          placeholder="Say something..."
          placeholderTextColor="#666"
          value={input}
          onChangeText={setInput}
          onSubmitEditing={sendMessage}
          returnKeyType="send"
          editable={!loading}
          multiline
        />
        <Pressable
          onPress={sendMessage}
          style={[styles.sendButton, (!input.trim() || loading) && styles.sendButtonDisabled]}
          disabled={!input.trim() || loading}
        >
          <Text style={styles.sendButtonText}>↑</Text>
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0a0a',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 16,
    paddingBottom: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#1a1a1a',
  },
  headerAvatar: {
    width: 32,
    height: 32,
    borderRadius: 16,
  },
  headerTitle: {
    color: '#fff',
    fontSize: 17,
    fontWeight: '600',
  },
  messages: {
    flex: 1,
  },
  messagesContent: {
    padding: 16,
    gap: 12,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 8,
  },
  rowUser: {
    justifyContent: 'flex-end',
  },
  rowAssistant: {
    justifyContent: 'flex-start',
  },
  avatar: {
    width: 28,
    height: 28,
    borderRadius: 14,
  },
  bubble: {
    maxWidth: '75%',
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 18,
  },
  bubbleUser: {
    backgroundColor: '#ff1f57',
    borderBottomRightRadius: 4,
  },
  bubbleAssistant: {
    backgroundColor: '#1a1a1a',
    borderBottomLeftRadius: 4,
  },
  bubbleText: {
    fontSize: 15,
    lineHeight: 21,
  },
  bubbleTextUser: {
    color: '#fff',
  },
  bubbleTextAssistant: {
    color: '#e5e5e5',
  },
  inputBar: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 8,
    paddingHorizontal: 12,
    paddingTop: 10,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#1a1a1a',
  },
  modelSelector: {
    position: 'relative',
    marginBottom: 2,
  },
  modelButton: {
    paddingVertical: 8,
    paddingHorizontal: 10,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: '#2a2a2a',
    backgroundColor: '#111',
  },
  modelButtonText: {
    color: '#ddd',
    fontSize: 12,
  },
  modelMenu: {
    position: 'absolute',
    bottom: 44,
    left: 0,
    minWidth: 140,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: '#2a2a2a',
    backgroundColor: '#111',
    paddingVertical: 6,
    zIndex: 20,
  },
  modelMenuItem: {
    paddingVertical: 10,
    paddingHorizontal: 12,
  },
  modelMenuText: {
    color: '#ddd',
    fontSize: 12,
  },
  modelMenuTextActive: {
    color: '#fff',
    fontWeight: '600',
  },
  input: {
    flex: 1,
    backgroundColor: '#1a1a1a',
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingTop: 10,
    paddingBottom: 10,
    fontSize: 15,
    color: '#fff',
    maxHeight: 100,
  },
  sendButton: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: '#ff1f57',
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendButtonDisabled: {
    backgroundColor: '#1a1a1a',
  },
  sendButtonText: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '700',
  },
});
