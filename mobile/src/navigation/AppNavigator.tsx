import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import Ionicons from '@expo/vector-icons/Ionicons';
import { DefaultTheme, DarkTheme } from '@react-navigation/native';
import React from 'react';
import { ActivityIndicator, View } from 'react-native';
import { useAuth } from '../context/AuthContext';
import { useAppTheme } from '../context/ThemeContext';
import { AuthScreen } from '../screens/AuthScreen';
import { CourseDetailScreen } from '../screens/CourseDetailScreen';
import { CoursesScreen } from '../screens/CoursesScreen';
import { DashboardScreen } from '../screens/DashboardScreen';
import { LearningScreen } from '../screens/LearningScreen';
import { RecruitmentScreen } from '../screens/RecruitmentScreen';
import { SettingsScreen } from '../screens/SettingsScreen';

const Stack = createNativeStackNavigator();
const Tab = createBottomTabNavigator();

function tabIcon(routeName: string, focused: boolean) {
  const color = focused ? '#2563eb' : '#64748b';
  const size = 20;
  if (routeName === 'Dashboard') return <Ionicons name={focused ? 'grid' : 'grid-outline'} color={color} size={size} />;
  if (routeName === 'Courses') return <Ionicons name={focused ? 'book' : 'book-outline'} color={color} size={size} />;
  if (routeName === 'Learning') return <Ionicons name={focused ? 'school' : 'school-outline'} color={color} size={size} />;
  if (routeName === 'Recruitment') return <Ionicons name={focused ? 'briefcase' : 'briefcase-outline'} color={color} size={size} />;
  return <Ionicons name={focused ? 'settings' : 'settings-outline'} color={color} size={size} />;
}

function MainTabs() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerStyle: { backgroundColor: '#f8fafc' },
        headerTitleStyle: { fontWeight: '700' },
        tabBarStyle: { height: 64, paddingBottom: 8, paddingTop: 6 },
        tabBarActiveTintColor: '#2563eb',
        tabBarInactiveTintColor: '#64748b',
        tabBarIcon: ({ focused }) => tabIcon(route.name, focused),
      })}
    >
      <Tab.Screen name="Dashboard" component={DashboardScreen} options={{ title: 'Tong quan' }} />
      <Tab.Screen name="Courses" component={CoursesScreen} options={{ title: 'Khoa hoc' }} />
      <Tab.Screen name="Learning" component={LearningScreen} options={{ title: 'Hoc tap' }} />
      <Tab.Screen name="Recruitment" component={RecruitmentScreen} options={{ title: 'Tuyen GV' }} />
      <Tab.Screen name="Settings" component={SettingsScreen} options={{ title: 'Cai dat' }} />
    </Tab.Navigator>
  );
}

export function AppNavigator() {
  const { user, loading } = useAuth();
  const { theme } = useAppTheme();
  const navTheme = theme.mode === 'dark' ? DarkTheme : DefaultTheme;
  if (loading) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.bg }}>
        <ActivityIndicator size="large" color={theme.primary} />
      </View>
    );
  }
  return (
    <NavigationContainer theme={navTheme}>
      <Stack.Navigator>
        {!user ? (
          <Stack.Screen name="Auth" component={AuthScreen} options={{ headerShown: false }} />
        ) : (
          <>
            <Stack.Screen name="Main" component={MainTabs} options={{ headerShown: false }} />
            <Stack.Screen name="CourseDetail" component={CourseDetailScreen} options={{ title: 'Chi tiet khoa hoc' }} />
          </>
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}
